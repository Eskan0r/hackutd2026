"""Event chain integrity and the lab/control-plane contract (D8, section 9.2).

ares/events.py is stdlib-only because the lab services run on bare
python:3.12-slim; these tests also pin the two things the lab depends on -- the
`emit()` signature and the on-disk line format that lab/selftest.sh greps.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor

import pytest

from ares.contracts import Event
from ares.events import (
    GENESIS,
    EventWriter,
    emit,
    read_events,
    serialize,
    verify_chain,
    writer_for,
)


@pytest.fixture(autouse=True)
def lab_env(tmp_path, monkeypatch):
    """The env the lab containers provide (lab/docker-compose.yml)."""
    monkeypatch.setenv("EVENTS_DIR", str(tmp_path))
    monkeypatch.setenv("EVENT_SOURCE", "fake")
    monkeypatch.setenv("RUN_ID", "r_01JC3")
    monkeypatch.setenv("TRIAL", "7")
    monkeypatch.setenv("VARIANT", "B")
    from ares import events
    events._WRITERS.clear()  # the writer cache is process-wide
    yield tmp_path


def test_env_configured_emit_matches_the_lab_contract(lab_env):
    ev = emit("answer-key", "http", "fire", bait_id="ak-01", dst_host="grader.acme.test")
    assert ev["run_id"] == "r_01JC3" and ev["trial"] == 7 and ev["variant"] == "B"
    assert ev["source"] == "answer-key"       # per-event source...
    assert (lab_env / "fake.jsonl").exists()  # ...is not the filename
    assert ev["prev_sha256"] == GENESIS
    # Full section 9.2 shape even for keys the caller omitted.
    for key in ("flaw", "dst_port", "method", "path", "token_match", "detail"):
        assert key in ev


def test_lab_call_sites_validate_against_the_pydantic_contract(lab_env):
    """The exact kwargs lab/leakbox/proxy.py and lab/services/fake.py pass.

    The lab cannot import pydantic, so nothing validates at write time; the
    control plane validates on read. If these two drift apart, the defender
    cannot parse the lab's events at all.
    """
    emit("leakbox-proxy", "http", "watch", bait_id=None, flaw=None,
         dst_host="outside.ares.test", dst_port=80, method="GET", path="/",
         token_match=False, detail={"decision": "blocked"})
    emit("pkg-proxy", "http", "fire", bait_id="outside-01", flaw="fetch_through",
         dst_host="pkg.acme.test", dst_port=80, method="GET", path="/",
         token_match=True, detail={})

    for raw in read_events(lab_env / "fake.jsonl"):
        Event.model_validate(raw)  # extra="forbid": any drift fails here


def test_on_disk_format_keeps_selftest_greps_working(lab_env):
    """lab/selftest.sh greps '"bait_id": "ak-01"' -- with the space."""
    emit("answer-key", "http", "fire", bait_id="ak-01")
    emit("pkg-proxy", "http", "fire", flaw="fetch_through")
    text = (lab_env / "fake.jsonl").read_text()
    assert '"bait_id": "ak-01"' in text
    assert '"flaw": "fetch_through"' in text
    assert '"severity": "fire"' in text
    assert '"prev_sha256"' in text


def test_unknown_kwargs_land_in_detail_not_top_level(lab_env):
    ev = emit("board", "http", "watch", detail={"a": 1}, rule="some_new_rule")
    assert ev["detail"] == {"a": 1, "rule": "some_new_rule"}
    assert "rule" not in {k for k in ev if k != "detail"}
    Event.model_validate(ev)


def test_chain_links_and_first_line_is_genesis(lab_env):
    for i in range(5):
        emit("leakbox-proxy", "http", "info", dst_port=i)
    path = lab_env / "fake.jsonl"
    events = list(read_events(path))
    assert events[0]["prev_sha256"] == GENESIS
    assert len(events) == 5 and verify_chain(path) == []


def test_tampering_with_any_line_is_detected(lab_env):
    """The case that matters: someone edits a `fire` down to an `info`."""
    emit("leakbox-proxy", "http", "info")
    emit("answer-key", "http", "fire", bait_id="ak-01")
    emit("leakbox-proxy", "http", "info")
    path = lab_env / "fake.jsonl"

    lines = path.read_text().splitlines()
    doctored = json.loads(lines[1])
    assert doctored["severity"] == "fire"
    doctored["severity"] = "info"
    lines[1] = serialize(doctored)
    path.write_text("\n".join(lines) + "\n")

    problems = verify_chain(path)
    assert problems, "editing a fire down to an info must break the chain"
    assert "fake.jsonl:3" in problems[0]


def test_deleting_a_line_is_detected(lab_env):
    for i in range(4):
        emit("leakbox-proxy", "http", "info", dst_port=i)
    path = lab_env / "fake.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:1] + lines[2:]) + "\n")
    assert verify_chain(path)


def test_truncation_leaves_a_valid_prefix(lab_env):
    """Dropping trailing lines cannot be caught from the chain alone; the scorer
    compares the tail hash against the signed report instead."""
    for i in range(4):
        emit("leakbox-proxy", "http", "info", dst_port=i)
    path = lab_env / "fake.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2]) + "\n")
    assert verify_chain(path) == []
    assert len(list(read_events(path))) == 2


def test_threading_http_server_shape_keeps_the_chain_intact(lab_env):
    """The lab services are ThreadingHTTPServer: many threads, one process."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: emit("fake", "http", "info", dst_port=i), range(40)))
    path = lab_env / "fake.jsonl"
    assert len(list(read_events(path))) == 40
    assert verify_chain(path) == []


def test_two_writer_objects_on_one_file(lab_env):
    a = EventWriter(lab_env, "shared")
    b = EventWriter(lab_env, "shared")
    a.emit("x", "http", "info")
    b.emit("y", "http", "info")
    a.emit("x", "http", "info")  # a's cached tail is now stale
    b.emit("y", "http", "info")
    path = lab_env / "shared.jsonl"
    assert verify_chain(path) == []
    assert len(list(read_events(path))) == 4


def test_writer_for_is_shared_per_file(lab_env):
    assert writer_for() is writer_for()
    assert writer_for(lab_env, "a") is not writer_for(lab_env, "b")


def _append(args):
    """Separate process: the real case flock exists for."""
    d, n = args
    os.environ["EVENTS_DIR"] = d
    w = EventWriter(d, "shared")
    for i in range(n):
        w.emit("proxy", "http", "info", dst_port=i)
    return os.getpid()


def test_concurrent_processes_keep_the_chain_intact(lab_env):
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(_append, [(str(lab_env), 5)] * 4))
    path = lab_env / "shared.jsonl"
    assert len(list(read_events(path))) == 20
    assert verify_chain(path) == []
