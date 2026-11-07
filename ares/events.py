"""Append-only, hash-chained JSONL event log (ARCHITECTURE.md D8, section 9.2).

The lab has no network path to the control plane: producers inside `labnet`
append lines to a shared volume and the defender tails them. The chain makes the
log tamper-evident -- editing or deleting a line breaks every `prev_sha256`
after it.

Who may write: the Leakbox policy proxy, the fake services, the DNS sinkhole and
the LLM gateway. The agent sandbox must NOT have the event volume mounted
(ARCHITECTURE.md section 3), so nothing the agent runs can forge, truncate or
suppress evidence.

Each producer writes its own file (`<source>.jsonl`) under the run's events
directory. Per-file chains keep writers independent while staying append-only;
the defender merges by timestamp. `flock` makes concurrent appends from separate
processes safe.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

from ares.contracts import Event

try:  # POSIX only; the lab is Linux containers, but keep imports importable on any host
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

GENESIS = "0" * 64


def canonical_json(obj: Dict[str, Any]) -> bytes:
    """Sorted keys, no whitespace -- the same form the report signer uses."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _line_hash(line: Union[str, bytes]) -> str:
    if isinstance(line, str):
        line = line.encode("utf-8")
    return sha256_hex(line.strip())


class EventWriter:
    """Appends events to one JSONL file, chaining each to the previous line.

    `prev_sha256` is assigned here rather than by the caller so a producer cannot
    accidentally (or deliberately) break the chain.
    """

    def __init__(self, events_dir: Union[str, Path], source: str) -> None:
        self.source = source
        self.dir = Path(events_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / ("%s.jsonl" % source)
        self._last: Optional[str] = None   # hash of the last line we know about
        self._size: int = -1               # file size when we learned that hash

    def _read_tail_hash(self) -> str:
        """Hash of the last line actually on disk."""
        tail = GENESIS
        if self.path.exists():
            with self.path.open("rb") as fh:
                last = b""
                for raw in fh:
                    if raw.strip():
                        last = raw
                if last:
                    tail = _line_hash(last)
        return tail

    def emit(self, event: Event) -> Event:
        """Chain, append and fsync one event. Returns the stored event."""
        if event.source != self.source:
            raise ValueError(
                "writer for %r cannot emit an event from %r" % (self.source, event.source)
            )
        with self.path.open("ab") as fh:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                if size == 0:
                    prev = GENESIS
                elif self._last is None or size != self._size:
                    # The file grew since we last wrote, so another writer (or
                    # another process) owns the current tail. Chaining onto our
                    # cached hash here would break the chain, and a broken chain
                    # reads as tampering -- re-read instead.
                    prev = self._read_tail_hash()
                else:
                    prev = self._last
                event = event.model_copy(update={"prev_sha256": prev})
                line = canonical_json(event.model_dump(mode="json"))
                fh.write(line + b"\n")
                fh.flush()
                os.fsync(fh.fileno())
                self._last = _line_hash(line)
                self._size = fh.tell()
            finally:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return event


def read_events(path: Union[str, Path]) -> Iterator[Event]:
    p = Path(path)
    if not p.exists():
        return
    with p.open("r", encoding="utf-8") as fh:
        for raw in fh:
            if raw.strip():
                yield Event.model_validate_json(raw)


def verify_chain(path: Union[str, Path]) -> List[str]:
    """Return a list of problems. Empty list means the chain is intact."""
    p = Path(path)
    problems: List[str] = []
    if not p.exists():
        return ["%s: missing" % p]
    prev = GENESIS
    with p.open("rb") as fh:
        for n, raw in enumerate(fh, start=1):
            if not raw.strip():
                continue
            try:
                event = Event.model_validate_json(raw)
            except Exception as exc:  # malformed line breaks the audit trail
                problems.append("%s:%d: unparseable (%s)" % (p.name, n, exc))
                return problems
            if event.prev_sha256 != prev:
                problems.append(
                    "%s:%d: prev_sha256 %s, expected %s"
                    % (p.name, n, event.prev_sha256, prev)
                )
            prev = _line_hash(raw)
    return problems
