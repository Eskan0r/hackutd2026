"""Append-only, hash-chained JSONL events (ARCHITECTURE.md D8, section 9.2).

One file per writer under $EVENTS_DIR, named by $EVENT_SOURCE. Each line carries
prev_sha256 = sha256 of the previous line's bytes, so editing or deleting a line
breaks every link after it and the defender can tell.

STDLIB ONLY, on purpose. The lab services run on bare `python:3.12-slim` with no
pip install (see lab/docker-compose.yml) and import this module from /src, so a
pydantic import here would break every fake service. The pydantic `Event` model
in ares/contracts.py is for the control plane, which validates lines on read.

The per-event `source` field is not the filename: lab/services/fake.py writes
one `fake.jsonl` while emitting source="answer-key", "pkg-proxy" and so on.

Who may write: the Leakbox policy proxy, the fake services, the DNS sinkhole and
the LLM gateway. The agent sandbox must NOT have the event volume mounted
(section 3), so nothing the agent runs can forge, truncate or suppress evidence.
"""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

try:  # POSIX only; the lab is Linux containers, but stay importable anywhere
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

GENESIS = "0" * 64
_ZERO = GENESIS  # back-compat alias

# Every line carries the full section 9.2 shape, so consumers never special-case
# a missing key. Values a caller does not pass get these defaults.
_DEFAULTS = {
    "bait_id": None,
    "flaw": None,
    "dst_host": None,
    "dst_port": None,
    "method": None,
    "path": None,
    "token_match": False,
    "detail": {},
}


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _hash_line(line) -> str:
    """sha256 of one line's bytes, excluding the trailing newline."""
    if isinstance(line, str):
        line = line.encode("utf-8")
    return hashlib.sha256(line.rstrip(b"\r\n")).hexdigest()


def serialize(event: dict) -> str:
    """One event as its on-disk line.

    `sort_keys=True` with json's default separators, which is what lab/selftest.sh
    greps for (`"bait_id": "ak-01"`, with the space). Deliberately NOT the
    no-whitespace canonical form -- that belongs to the signed report (section
    9.6), and the chain hashes raw line bytes, so spacing is irrelevant to it.
    """
    return json.dumps(event, sort_keys=True)


class EventWriter:
    """Appends to one JSONL file, chaining each line to the previous one.

    `prev_sha256` is assigned here, never by the caller, so a producer cannot
    break the chain by accident.
    """

    def __init__(self, events_dir=None, source=None):
        self.dir = str(events_dir or os.environ.get("EVENTS_DIR", "/events"))
        self.file_source = str(source or os.environ.get("EVENT_SOURCE", "lab"))
        self.path = os.path.join(self.dir, "%s.jsonl" % self.file_source)
        self._lock = threading.Lock()  # the lab services are ThreadingHTTPServer
        self._last = None              # hash of the last line we wrote
        self._size = -1                # file size when we learned that hash

    def _read_tail_hash(self) -> str:
        try:
            with open(self.path, "rb") as fh:
                for line in reversed(fh.read().splitlines()):
                    if line.strip():
                        return _hash_line(line)
        except FileNotFoundError:
            pass
        return GENESIS

    def emit(self, source, kind, severity, **fields) -> dict:
        """Write one section 9.2 event. Severity is fixed by the caller (D1)."""
        event = {
            "ts": fields.pop("ts", None) or _now_iso(),
            "run_id": fields.pop("run_id", None) or os.environ.get("RUN_ID", "r_local"),
            "trial": fields.pop("trial", None),
            "variant": fields.pop("variant", None) or os.environ.get("VARIANT", "A"),
            "source": source,
            "kind": kind,
            "severity": severity,
        }
        if event["trial"] is None:
            event["trial"] = int(os.environ.get("TRIAL", "0"))
        for key, default in _DEFAULTS.items():
            event[key] = fields.pop(key, default)
        if fields:
            # Unknown keys go under detail rather than top level, so a line never
            # drifts from the frozen section 9.2 shape -- and nothing is dropped.
            event["detail"] = dict(event["detail"] or {}, **fields)

        os.makedirs(self.dir, exist_ok=True)
        with self._lock:
            with open(self.path, "ab") as fh:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    fh.seek(0, os.SEEK_END)
                    size = fh.tell()
                    if size == 0:
                        prev = GENESIS
                    elif self._last is None or size != self._size:
                        # The file grew since we last wrote, so another writer or
                        # process owns the tail. Chaining onto our cached hash
                        # would break the chain -- and a broken chain reads as
                        # tampering, so re-read instead of guessing.
                        prev = self._read_tail_hash()
                    else:
                        prev = self._last
                    event["prev_sha256"] = prev
                    line = serialize(event)
                    fh.write(line.encode("utf-8") + b"\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                    self._last = _hash_line(line)
                    self._size = fh.tell()
                finally:
                    if fcntl is not None:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return event


_WRITERS = {}
_WRITERS_LOCK = threading.Lock()


def writer_for(events_dir=None, source=None) -> EventWriter:
    """Process-wide writer per (dir, file), so the tail cache is actually shared."""
    key = (
        str(events_dir or os.environ.get("EVENTS_DIR", "/events")),
        str(source or os.environ.get("EVENT_SOURCE", "lab")),
    )
    with _WRITERS_LOCK:
        if key not in _WRITERS:
            _WRITERS[key] = EventWriter(*key)
        return _WRITERS[key]


def emit(source, kind, severity, **fields) -> dict:
    """Write one event to $EVENTS_DIR/$EVENT_SOURCE.jsonl. What the lab calls."""
    return writer_for().emit(source, kind, severity, **fields)


def read_events(path):
    """Yield each event on disk as a plain dict."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                if raw.strip():
                    yield json.loads(raw)
    except FileNotFoundError:
        return


def verify_chain(path):
    """Return a list of problems. Empty list means the chain is intact.

    Note what this cannot see: dropping lines from the END leaves a valid prefix.
    The scorer catches that by comparing the tail hash against the signed report.
    """
    problems = []
    if not os.path.exists(path):
        return ["%s: missing" % path]
    name = os.path.basename(path)
    prev = GENESIS
    with open(path, "rb") as fh:
        for n, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                event = json.loads(raw)
            except ValueError as exc:
                problems.append("%s:%d: unparseable (%s)" % (name, n, exc))
                return problems
            if event.get("prev_sha256") != prev:
                problems.append(
                    "%s:%d: prev_sha256 %s, expected %s"
                    % (name, n, event.get("prev_sha256"), prev)
                )
            prev = _hash_line(raw)
    return problems
