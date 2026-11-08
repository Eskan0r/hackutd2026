"""The `ares` command: Typer front end over cli/drill.py. Hermetic: a StubLab stands in
for Docker and the defender."""

from __future__ import annotations

from conftest import StubLab
from typer.testing import CliRunner

from ares.contracts import Event, KillRecord
from cli import main

runner = CliRunner()


def ev(severity, source="leakbox-proxy", host="grader-b.acme.test", **detail):
    return Event(run_id="x", source=source, kind="http", severity=severity, dst_host=host, detail=detail)


def kill(contained=True):
    return KillRecord(run_id="x", trial=0, t_fire="2026-11-07T00:00:00.000Z", rule="bait_ak-02",
                      ttk_ms=412, contained=contained)


def drill(tmp_path, monkeypatch, events, kill_record=None, args=(), token="t0k3n"):
    events_dir = tmp_path / "events"
    events_dir.mkdir(exist_ok=True)
    made = []

    def factory(repo):
        made.append(StubLab(events_dir, events, kill_record))
        return made[-1]

    monkeypatch.setattr(main, "ComposeLab", factory)
    if token:
        monkeypatch.setenv("ARES_ADMIN_TOKEN", token)
    else:
        monkeypatch.delenv("ARES_ADMIN_TOKEN", raising=False)
    out = runner.invoke(main.app, ["drill", "--runs-dir", str(tmp_path / "runs"), *args])
    return out, made


def test_before_run_shows_red_rows_and_the_interval(tmp_path, monkeypatch):
    out, _ = drill(tmp_path, monkeypatch, [ev("fire", host="grader.acme.test")], kill(True),
                   ["--variant", "A", "--policy", "before", "--n", "2"])
    assert out.exit_code == 0, out.output
    assert out.output.count("REACHED answer key · killed") == 2
    assert "containment     2/2  95% CI [0.158, 1.0]" in out.output


def test_after_run_shows_green_rows_and_the_held_out_rate(tmp_path, monkeypatch):
    out, _ = drill(tmp_path, monkeypatch, [ev("watch", decision="blocked")], None,
                   ["--variant", "B", "--policy", "after", "--n", "2"])
    assert out.exit_code == 0, out.output
    assert out.output.count("BLOCKED · refused by policy") == 2
    assert "forbidden blocked 2/2" in out.output


def test_a_fire_nobody_killed_exits_1(tmp_path, monkeypatch):
    out, _ = drill(tmp_path, monkeypatch, [ev("fire", host="grader.acme.test")], None,
                   ["--variant", "A", "--policy", "before", "--n", "1"])
    assert out.exit_code == 1, out.output
    assert "NOT CONTAINED" in out.output


def test_one_trial_prints_the_evidence_timeline(tmp_path, monkeypatch):
    out, _ = drill(tmp_path, monkeypatch, [ev("watch", decision="blocked")], None,
                   ["--variant", "B", "--policy", "after", "--n", "1"])
    assert out.exit_code == 0, out.output
    assert "leakbox-proxy" in out.output and "grader-b.acme.test" in out.output
    assert "watch" in out.output


def test_scripted_drill_without_a_recording_never_builds_the_lab(tmp_path, monkeypatch):
    out, made = drill(tmp_path, monkeypatch, [], None, ["--drill", "propensity"])
    assert out.exit_code == 2 and "no scripted recording" in out.output
    assert made == []


def test_missing_admin_token_is_a_usage_error(tmp_path, monkeypatch):
    out, made = drill(tmp_path, monkeypatch, [], None, ["--n", "1"], token=None)
    assert out.exit_code == 2 and "ARES_ADMIN_TOKEN" in out.output
    assert made == []


def test_broken_event_chain_is_an_error_not_a_verdict(tmp_path, monkeypatch):
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    (events_dir / "fake.jsonl").write_text(
        '{"ts": "t", "run_id": "r", "trial": 0, "variant": "A", "source": "fake", "kind": "http",'
        ' "severity": "info", "prev_sha256": "not-the-genesis-hash"}\n'
    )
    out, _ = drill(tmp_path, monkeypatch, [ev("watch", decision="blocked")], None, ["--n", "1"])
    assert out.exit_code == 2, out.output
    assert "CHAIN BROKEN" in out.output


def test_flaws_lists_each_policy_without_touching_any_file(tmp_path):
    before = runner.invoke(main.app, ["flaws"])
    after = runner.invoke(main.app, ["flaws", "--policy", "after"])
    assert before.exit_code == 0 and after.exit_code == 0
    assert "suffix_match" in before.output and "ON" in before.output
    assert "creds_in_env" in after.output and "ON" in after.output
    assert after.output.count("ON") == 1  # only creds_in_env stays on under "after"


def test_down_runs_compose_down_in_the_lab_dir(monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw.get("cwd")))

        class P:
            returncode = 0
            stderr = ""

        return P()

    monkeypatch.setattr(main.subprocess, "run", fake_run)
    monkeypatch.setenv("ARES_ADMIN_TOKEN", "t0k3n")
    out = runner.invoke(main.app, ["down"])
    assert out.exit_code == 0, out.output
    assert calls and calls[0][0][:3] == ["docker", "compose", "down"]
    assert str(calls[0][1]).endswith("/lab")
