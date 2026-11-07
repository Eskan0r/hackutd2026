"""Append-only, hash-chained JSONL events (ARCHITECTURE §8, §9.2).

One file per source under $EVENTS_DIR, named by $EVENT_SOURCE. Each line carries
prev_sha256 = sha256 of the previous line's bytes, so the defender can detect tampering.
"""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()
_ZERO = "0" * 64


def _path() -> str:
    return os.path.join(
        os.environ.get("EVENTS_DIR", "/events"),
        f"{os.environ.get('EVENT_SOURCE', 'lab')}.jsonl",
    )


def _last_sha(path: str) -> str:
    try:
        with open(path, "rb") as f:
            for line in reversed(f.read().splitlines()):
                if line.strip():
                    return hashlib.sha256(line).hexdigest()
    except FileNotFoundError:
        pass
    return _ZERO


def emit(source: str, kind: str, severity: str, **fields) -> dict:
    """Write one §9.2 event line. Severity is fixed by the caller, never a model."""
    event = {
        "ts": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "run_id": os.environ.get("RUN_ID", "r_local"),
        "trial": int(os.environ.get("TRIAL", "0")),
        "variant": os.environ.get("VARIANT", "A"),
        "source": source,
        "kind": kind,
        "severity": severity,
        "bait_id": fields.pop("bait_id", None),
        "flaw": fields.pop("flaw", None),
        **fields,
    }
    path = _path()
    with _LOCK:
        event["prev_sha256"] = _last_sha(path)
        line = json.dumps(event, sort_keys=True)
        with open(path, "a") as f:
            f.write(line + "\n")
    return event
