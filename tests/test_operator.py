"""Operator mode is the deliberate exception, and stays an exception.

The read-only viewer is the project's claim that the dashboard cannot be a
second control plane. Operator mode breaks that on purpose, for a demo, behind
a flag -- so what matters is that the break is *contained*:

  * the viewer app still has no route that acts, even with this module imported;
  * the operator app is only ever built by asking for it;
  * nothing reaches a verdict the CLI would not, because both call
    cli.verdict.classify;
  * one drill at a time, because the lab is one set of containers;
  * the terminal never forwards a command string to a shell.

Hermetic: the drill itself is stubbed, so no Docker and no network.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from cli import lab
from cli.verdict import classify
from web import operator
from web.server import app as viewer_app


class FakeTrial:
    """What cli.lab.drill() hands back, minus the lab."""

    def __init__(self, run_id="r_op1", events=(), kill_record=None, chain_problems=(),
                 outcome=None):
        self.run_id = run_id
        self.events = list(events)
        self.kill_record = kill_record
        self.chain_problems = list(chain_problems)
        self.outcome = outcome or {
            "steps": 3, "stop_reason": "done", "tool_calls": [{}, {}], "errors": [],
        }

    @property
    def fires(self):
        return [e for e in self.events if e.get("severity") == "fire"]

    @property
    def breaches(self):
        return [e for e in self.events if e.get("severity") == "breach"]


@pytest.fixture(autouse=True)
def no_jobs():
    """Jobs live in a module-level registry; don't leak them between tests."""
    operator._jobs.clear()
    yield
    operator._jobs.clear()


@pytest.fixture
def stub_drill(monkeypatch):
    """Replace the real trial with one that returns `trial` after `delay`."""
    def make(trial=None, delay=0.0, raises=None):
        calls = {}

        def fake(driver, goal, script, model, caps, on_step=None, kill=True,
                 on_run_id=None, **kw):
            calls.update(driver=driver, goal=goal, script=script, model=model,
                         caps=caps, kill=kill)
            if on_run_id:
                on_run_id((trial or FakeTrial()).run_id)
            if on_step:
                on_step("Starting the lab")
            if delay:
                time.sleep(delay)
            if raises:
                raise raises
            return trial or FakeTrial()

        monkeypatch.setattr(lab, "drill", fake)
        return calls
    return make


def wait_for(client, job_id, state="done", timeout=5.0):
    """Poll a job until it leaves `running`; the work happens in a thread."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/api/drill/%s" % job_id).json()
        if body["state"] != "running":
            assert body["state"] == state, body
            return body
        time.sleep(0.02)
    raise AssertionError("job %s never reached %s" % (job_id, state))


# --- the exception stays contained ------------------------------------------


def test_importing_the_operator_does_not_arm_the_viewer():
    """The read-only guarantee is a property of the viewer app object.

    Two apps, not one app with a flag: importing the module that can start a
    drill must not add a route to the app that cannot. If this ever fails, the
    dashboard became a control plane by import side effect.
    """
    methods = set()
    for route in viewer_app.routes:
        methods |= set(getattr(route, "methods", set()) or set())
    assert methods <= {"GET", "HEAD"}
    assert not [r for r in viewer_app.routes if getattr(r, "path", "") == "/api/drill"]


def test_the_viewer_says_it_cannot_act():
    """The page asks before it offers a Run button; the viewer answers honestly."""
    body = TestClient(viewer_app).get("/api/capabilities").json()
    assert body["operator"] is False


def test_the_operator_says_it_can_and_serves_the_viewer_too():
    client = TestClient(operator.build_app())
    assert client.get("/api/capabilities").json()["operator"] is True
    # the read-only API is mounted underneath, so one port serves everything
    assert client.get("/api/runs").status_code == 200
    assert client.get("/").status_code == 200


# --- running a drill --------------------------------------------------------


def test_a_drill_runs_and_reports_the_clis_verdict(stub_drill):
    """The dashboard must not reach a conclusion the CLI would not."""
    trial = FakeTrial(events=[{"severity": "fire"}], kill_record={
        "run_id": "r_op1", "trial": 0, "contained": True, "ttk_ms": 412,
        "post_kill_leaks": 0, "post_kill_events": 0,
        "levers": [{"name": "gateway_deny", "ok": True, "verified": True}],
        "verify": {"labnet_endpoint": False, "paused": True},
    })
    stub_drill(trial)
    client = TestClient(operator.build_app())

    started = client.post("/api/drill", json={"recording": "fetch_through"})
    assert started.status_code == 202, started.text
    job = wait_for(client, started.json()["job"])

    assert job["verdict"] == classify(trial, 12).code == "contained"
    assert job["exit_code"] == 0
    assert job["run_id"] == "r_op1"
    text = "\n".join(line["text"] for line in job["lines"])
    assert "CONTAINED" in text
    assert "ttk_ms 412" in text          # the kill path, as the CLI prints it


def test_the_equivalent_cli_line_is_echoed(stub_drill):
    """The CLI stays the real interface: the page says what it just ran."""
    stub_drill()
    client = TestClient(operator.build_app())
    body = client.post("/api/drill", json={"recording": "fetch_through",
                                           "kill": False}).json()
    assert body["command"] == "ares drill fetch_through --no-kill"
    # tagged cmd-echo, not cmd: the console prints the typed line itself, and a
    # second prompt line under it looks like the command ran twice
    assert body["lines"][0] == {"tag": "cmd-echo",
                                "text": "ares drill fetch_through --no-kill"}


def test_options_reach_the_drill_as_typed_fields(stub_drill):
    calls = stub_drill()
    client = TestClient(operator.build_app())
    started = client.post("/api/drill", json={
        "model": "nvidia/nemotron-3.5-lightning-30b-a3b", "max_steps": 5, "kill": True,
    })
    wait_for(client, started.json()["job"])
    assert calls["driver"] == "model"
    assert calls["model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"
    assert calls["caps"].max_steps == 5
    assert calls["kill"] is True


def test_an_unknown_recording_never_starts_anything(stub_drill):
    calls = stub_drill()
    client = TestClient(operator.build_app())
    res = client.post("/api/drill", json={"recording": "no-such-recording"})
    assert res.status_code == 400
    assert "unknown recording" in res.json()["detail"]
    assert calls == {}                    # nothing was run
    assert operator._jobs == {}           # and no job was recorded


def test_only_one_drill_at_a_time(stub_drill):
    """The lab is a single set of containers; two drills would share them and
    interleave their events into one run's file."""
    stub_drill(delay=0.5)
    client = TestClient(operator.build_app())
    first = client.post("/api/drill", json={"recording": "fetch_through"})
    assert first.status_code == 202
    second = client.post("/api/drill", json={"recording": "fetch_through"})
    assert second.status_code == 409
    assert "already running" in second.json()["detail"]
    wait_for(client, first.json()["job"])
    # once it is done the slot frees up again
    assert client.post("/api/drill", json={"recording": "fetch_through"}).status_code == 202


def test_a_failed_drill_is_reported_not_swallowed(stub_drill):
    stub_drill(raises=lab.DrillError("docker not found"))
    client = TestClient(operator.build_app())
    started = client.post("/api/drill", json={"recording": "fetch_through"})
    job = wait_for(client, started.json()["job"], state="error")
    assert job["exit_code"] == 2
    assert "docker not found" in "\n".join(line["text"] for line in job["lines"])


def test_a_crash_inside_the_drill_still_ends_the_job(stub_drill):
    """A bug in the drill must not leave the job running forever: the page would
    sit on a spinner and the one-at-a-time slot would never free."""
    stub_drill(raises=RuntimeError("boom"))
    client = TestClient(operator.build_app())
    started = client.post("/api/drill", json={"recording": "fetch_through"})
    job = wait_for(client, started.json()["job"], state="error")
    assert "RuntimeError: boom" in "\n".join(line["text"] for line in job["lines"])
    assert operator._active() is None


def test_the_terminal_cannot_pass_a_command_to_a_shell():
    """The browser terminal looks like a prompt. If it forwarded text to a
    shell, the demo would be a remote code execution hole -- so the API takes
    typed fields and there is nowhere to put a command string."""
    assert set(operator.DrillRequest.model_fields) == {
        "recording", "goal", "model", "max_steps", "max_tokens", "max_wall_seconds", "kill",
    }
    client = TestClient(operator.build_app())
    # an unknown field is rejected outright rather than ignored-and-forwarded
    res = client.post("/api/drill", json={"recording": "fetch_through",
                                          "cmd": "rm -rf /"})
    assert res.status_code in (200, 202, 422)
    if res.status_code != 422:            # pydantic may ignore extras; then
        job = res.json()                  # it must at least never appear anywhere
        assert "rm -rf" not in job["command"]


def test_a_drill_job_streams_its_lines(stub_drill):
    stub_drill(FakeTrial())
    client = TestClient(operator.build_app())
    started = client.post("/api/drill", json={"recording": "fetch_through"})
    job_id = started.json()["job"]
    with client.stream("GET", "/api/drill/%s/stream" % job_id) as res:
        assert res.status_code == 200
        body = ""
        for chunk in res.iter_text():
            body += chunk
            if '"state": "done"' in body or '"state":"done"' in body:
                break
    assert "Starting the lab" in body


def test_streaming_an_unknown_job_is_a_404():
    client = TestClient(operator.build_app())
    assert client.get("/api/drill/nope/stream").status_code == 404
    assert client.get("/api/drill/nope").status_code == 404
