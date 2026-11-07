"""Event chain integrity (ARCHITECTURE.md D8)."""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor

from ares.contracts import Event
from ares.events import GENESIS, EventWriter, read_events, verify_chain


def _ev(i: int, source: str = "leakbox-proxy") -> Event:
    return Event(run_id="r_x", trial=i, source=source, kind="http", severity="info")


def test_chain_links_and_first_line_is_genesis(tmp_path):
    w = EventWriter(tmp_path, "leakbox-proxy")
    for i in range(5):
        w.emit(_ev(i))
    path = tmp_path / "leakbox-proxy.jsonl"
    events = list(read_events(path))
    assert events[0].prev_sha256 == GENESIS
    assert len(events) == 5
    assert verify_chain(path) == []


def test_tampering_with_any_line_is_detected(tmp_path):
    """The case that matters: someone edits a `fire` down to an `info`."""
    w = EventWriter(tmp_path, "answer-key")
    w.emit(_ev(0, "answer-key"))
    w.emit(Event(run_id="r_x", trial=1, source="answer-key", kind="http",
                 severity="fire", bait_id="answer-key-01"))
    w.emit(_ev(2, "answer-key"))
    path = tmp_path / "answer-key.jsonl"

    lines = path.read_text().splitlines()
    doctored = json.loads(lines[1])
    assert doctored["severity"] == "fire"
    doctored["severity"] = "info"
    lines[1] = json.dumps(doctored, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n")

    problems = verify_chain(path)
    assert problems, "editing a fire down to an info must break the chain"
    assert "answer-key.jsonl:3" in problems[0]


def test_deleting_a_line_is_detected(tmp_path):
    w = EventWriter(tmp_path, "answer-key")
    for i in range(4):
        w.emit(_ev(i, "answer-key"))
    path = tmp_path / "answer-key.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:1] + lines[2:]) + "\n")
    assert verify_chain(path)


def test_truncation_leaves_a_valid_prefix(tmp_path):
    """Dropping trailing lines cannot be detected from the chain alone; the
    scorer compares the tail hash against the signed report instead."""
    w = EventWriter(tmp_path, "answer-key")
    for i in range(4):
        w.emit(_ev(i, "answer-key"))
    path = tmp_path / "answer-key.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2]) + "\n")
    assert verify_chain(path) == []
    assert len(list(read_events(path))) == 2


def test_second_writer_in_this_process_does_not_break_the_chain(tmp_path):
    a = EventWriter(tmp_path, "shared")
    b = EventWriter(tmp_path, "shared")
    a.emit(_ev(1, "shared"))
    b.emit(_ev(2, "shared"))
    a.emit(_ev(3, "shared"))   # a's cached tail is now stale
    b.emit(_ev(4, "shared"))
    path = tmp_path / "shared.jsonl"
    assert verify_chain(path) == []
    assert len(list(read_events(path))) == 4


def _append(args):
    """Separate process: the real case flock exists for."""
    d, n = args
    w = EventWriter(d, "shared")
    for i in range(n):
        w.emit(_ev(i, "shared"))
    return os.getpid()


def test_concurrent_processes_keep_the_chain_intact(tmp_path):
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(_append, [(str(tmp_path), 5)] * 4))
    path = tmp_path / "shared.jsonl"
    assert len(list(read_events(path))) == 20
    assert verify_chain(path) == []
