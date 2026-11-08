"""Defender tailer invariants (ARCHITECTURE.md D1, D3).

The first live drill ended with the bait taken and no lever pulled because a
non-event line in the events directory crashed the watcher. Whatever else is in
that directory, a fire event must still be seen.
"""

from __future__ import annotations

import json

from defender.watch import Tail

EVENT = {
    "ts": "2026-11-07T19:02:11.412Z",
    "run_id": "r_t",
    "trial": 0,
    "variant": "A",
    "source": "answer-key",
    "kind": "http",
    "severity": "fire",
    "bait_id": "ak-01",
    "dst_host": "grader.acme.test",
    "path": "/",
    "detail": {},
    "prev_sha256": "0" * 64,
}


def test_non_event_lines_in_the_events_dir_are_skipped_not_fatal(tmp_path):
    # What the gateway's transcript used to look like, sitting beside the chain.
    (tmp_path / "gateway-transcript.jsonl").write_text(
        json.dumps(
            {"ts": EVENT["ts"], "run_id": "r_t", "call": 1, "request": {"messages": []}}
        )
        + "\n"
        + "not even json\n"
    )
    (tmp_path / "fake.jsonl").write_text(json.dumps(EVENT) + "\n")

    events = Tail(str(tmp_path)).new_events()

    assert [e.severity for e in events] == ["fire"]
    assert events[0].bait_id == "ak-01"


def test_lab_identity_is_read_from_the_container_env():
    """The lab stamps events with its own RUN_ID/TRIAL; watching any other id is a
    false green, so the defender compares before it starts."""
    from ares.levers import env_identity

    attrs = {
        "Config": {
            "Env": ["PATH=/usr/bin", "RUN_ID=r_pilot_1", "TRIAL=3", "EVENT_SOURCE=fake"]
        }
    }
    assert env_identity(attrs) == ("r_pilot_1", 3)
    assert env_identity({"Config": {"Env": ["RUN_ID=r_local"]}}) == ("r_local", 0)
    assert env_identity({}) == (None, 0)


def test_off_contract_event_lines_still_count(tmp_path):
    bad = dict(EVENT, kind="not-a-real-kind")  # fails the Literal, but it is an event
    (tmp_path / "proxy.jsonl").write_text(json.dumps(bad) + "\n")

    events = Tail(str(tmp_path)).new_events()

    assert len(events) == 1 and events[0].severity == "fire"
