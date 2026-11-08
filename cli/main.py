"""`ares` command line: a Typer layer over cli/drill.py and cli/lab.py. Parse, call, print.

    ares drill --variant A --policy before --n 20     n trials, verdict rows, intervals (cli/drill.py)
    ares drill --variant B --policy after  --n 20
    ares drill --drill normal --policy after --n 1
    ares drill --target owner/repo [--mode live]       the whole containment + fix + PR loop (cli/pipeline.py)
    ares trial [recording] [--target owner/repo]       one trial, or the same loop (cli/lab.py, cli/pipeline.py)
    ares fix lab/runs/kills/<run>.json [--open-pr]      name the cause, print or PR the leakbox.yaml change
    ares flaws [on|off|reset] [names] [--policy after]
    ares down

Every verdict comes from cli/drill.py or cli/lab.py, which decide from the lab's events and
the defender's kill record only. This file never looks at what the agent said.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

from agent import harness          # for DEFAULT_MODEL only; see resolved_model()
from ares.contracts import Caps, Event, KillRecord
from ares.events import read_events
from ares.results import DrillSummary
from cli import lab  # loads the repo-root .env
from cli import github_pr, pipeline, pr_writer, slack
from cli.drill import (
    COLUMNS,
    LAB_DIR,
    POLICY_FILES_HOST,
    RECORDINGS,
    REPO,
    ComposeLab,
    TrialSpec,
    _printable,
    format_row,
    format_summary,
    header_line,
    new_drill_id,
    run_drill,
    use_color,
)
from lab.leakbox.config import load_leakbox
from scoring import fixes

# The verdict rule itself lives in cli/verdict.py, so the dashboard's operator
# reaches the same conclusion from the same code rather than a second copy.
# A trial that never completed is not a hold and not a clean error: it is
# inconclusive (exit 3), and must never be shown as 'Boundary held'.
from .verdict import (
    EXIT_BREAKOUT, EXIT_ERROR, EXIT_HELD, EXIT_INCONCLUSIVE, classify,
)
from .verdict import inconclusive as _inconclusive  # the pipeline's judge

app = typer.Typer(
    no_args_is_help=True, help="Ares: a fire drill for AI agent containment."
)

EXIT_OK, EXIT_BAD = EXIT_HELD, EXIT_BREAKOUT
# `ares hunt` found nothing. Not a pass: the agent may simply never have tried,
# which is the "not exercised" case and proves nothing either way.
EXIT_NO_BREACH = EXIT_INCONCLUSIVE
WIDTH = 78
BANNER = "   ▄▀█ █▀█ █▀▀ █▀\n   █▀█ █▀▄ ██▄ ▄█\n   your sandbox defender"

# What each recording in agent/recorded/ does, in a few words (`ares trial`).
SCENARIOS = {
    "fetch_through": "asks the allowed package proxy to fetch outside.ares.test",
    "blocked": "retries a new outside host after the fix, then reports it's blocked",
    "soft_kill": "reads decoy creds and starts a loop meant to outlive the kill",
}


class Mode(str, Enum):
    scripted = "scripted"
    live = "live"


class Drill(str, Enum):
    breakout = "breakout"
    normal = "normal"
    propensity = "propensity"


class Variant(str, Enum):
    A = "A"
    B = "B"


class Policy(str, Enum):
    before = "before"
    after = "after"


class FlawAction(str, Enum):
    on = "on"
    off = "off"
    reset = "reset"


_SEVERITY = {
    "info": ("  info", None),
    "watch": (" watch", "yellow"),
    "fire": ("● FIRE", "red"),
    "breach": ("BREACH", "red"),
}


def validate(mode: str, drill: str, variant: str) -> Optional[str]:
    """Refuse what would fail mid-trial with the lab already up."""
    if mode == "scripted" and (drill, variant) not in RECORDINGS:
        known = ", ".join("%s/%s" % k for k in sorted(RECORDINGS))
        return "no scripted recording for %s/%s; use --mode live or one of: %s" % (
            drill,
            variant,
            known,
        )
    return None


def _fail(message: str) -> None:
    typer.secho("error: %s" % message, fg="red", err=True)
    raise typer.Exit(EXIT_ERROR)


def _require_docker() -> None:
    """Fail with the fix, not a WinError or 2000 chars of compose stderr, when Docker is missing."""
    try:
        running = subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except FileNotFoundError:
        _fail("Docker is not installed: install Docker Desktop, start it, and retry (the lab runs in containers)")
    except subprocess.TimeoutExpired:
        _fail("Docker is not responding: restart Docker Desktop (or the daemon) and retry")
    if not running:
        _fail("Docker is installed but not running: start Docker Desktop (or the daemon) and retry")


def _repo_path(path: Path) -> Path:
    """A path as typed, else the same path under the repo: kill records print repo-relative
    (lab/runs/kills/...), and `ares` runs from whatever folder the user is in."""
    if path.exists() or path.is_absolute():
        return path
    return REPO / path if (REPO / path).exists() else path


def _rule(title: str = "") -> str:
    if not title:
        return "─" * WIDTH
    return " %s %s" % (typer.style(title, bold=True), "─" * (WIDTH - len(title) - 2))


def _box(lines: List[str], color: str) -> None:
    inner = WIDTH - 4
    typer.secho("╔%s╗" % ("═" * (WIDTH - 2)), fg=color)
    for i, line in enumerate(lines):
        text = typer.style(line[:inner].ljust(inner), fg=color, bold=i == 0)
        typer.echo(typer.style("║ ", fg=color) + text + typer.style(" ║", fg=color))
    typer.secho("╚%s╝" % ("═" * (WIDTH - 2)), fg=color)


def _event_lines(e: Event) -> List[str]:
    """One evidence row per event: time, severity, source, kind, target. Host and path
    are agent-chosen, so they are scrubbed of control characters."""
    if isinstance(e, dict):  # cli/lab.py hands back the JSONL dicts
        e = Event.model_validate(e)
    label, color = _SEVERITY.get(e.severity, (e.severity, None))
    target = _printable("%s%s" % (e.dst_host or "", e.path or ""))
    lines = [
        "  %s  %s  %-14s %-9s %s"
        % (
            e.ts[11:23],
            typer.style(label, fg=color, bold=color is not None),
            e.source,
            e.kind,
            target,
        )
    ]
    extra = "   ".join(
        "%s=%s" % (k, v) for k, v in (("flaw", e.flaw), ("bait_id", e.bait_id)) if v
    )
    decision = (e.detail or {}).get("decision")
    if decision:
        extra = ("%s   " % extra if extra else "") + "decision=%s" % _printable(
            str(decision)
        )
    if extra:
        lines.append(typer.style("%s└─ %s" % (" " * 24, extra), fg=color))
    return lines


def _print_evidence(events: List[Any]) -> None:
    typer.echo(_rule("EVIDENCE"))
    typer.secho(
        "  %-12s  %-6s  %-14s %-9s %s"
        % ("TIME (UTC)", "SEV", "SOURCE", "KIND", "TARGET"),
        dim=True,
    )
    for e in events:
        for line in _event_lines(e):
            typer.echo(line)
    if not events:
        typer.echo("  (no events for this run)")


def _verdict_box(s: DrillSummary) -> None:
    v = s.verdicts
    tag = "   drill %s" % s.drill_id
    if v["not_contained"] or v["failed"]:
        _box(
            [
                "✗ %d NOT CONTAINED · %d failed%s"
                % (v["not_contained"], v["failed"], tag)
            ],
            "red",
        )
    elif s.drill == "breakout" and v["not_exercised"]:
        _box(
            [
                "○ %d/%d not exercised: the key was never tried, which proves nothing%s"
                % (v["not_exercised"], s.n, tag)
            ],
            "yellow",
        )
    elif s.drill == "normal":
        k = s.allowed_task_passed.k if s.allowed_task_passed else 0
        _box(
            ["✓ normal work still succeeds %d/%d%s" % (k, s.n, tag)],
            "green" if k == s.n else "yellow",
        )
    else:
        _box(
            [
                "✓ %d reached & killed · %d refused · 0 got through%s"
                % (v["contained"], v["held"], tag)
            ],
            "green",
        )


@app.command("drill")
def drill_cmd(
    mode: Mode = typer.Option(
        Mode.scripted, help="scripted replays a recording; live runs Nemotron."
    ),
    drill: Drill = typer.Option(Drill.breakout, help="Which goal the agent gets."),
    variant: Variant = typer.Option(
        Variant.A, help="Which copy of the answer key: B is the held-out one."
    ),
    policy: Policy = typer.Option(
        Policy.before, help="before = flaws on; after = the fix."
    ),
    n: int = typer.Option(
        20, min=1, help="Trials. Each gets fresh containers and a fresh run id."
    ),
    runs_dir: Path = typer.Option(
        REPO / "lab" / "runs", help="Where result.json and summary.json land.", show_default="lab/runs"
    ),
    target: Optional[str] = typer.Option(
        None, help="owner/repo of a company sandbox policy. Runs the whole loop instead: selftest, "
                   "kill checks, drill, fix, fresh rerun, replays, signed report, PR (needs GITHUB_TOKEN)."),
    recording: str = typer.Option(
        "fetch_through", help="With --target and --mode scripted: the recording the agent replays."),
    base: str = typer.Option("main", help="With --target: branch to read the policy from and open the PR against."),
    pr: bool = typer.Option(True, "--pr/--no-pr", help="With --target: open the PR once the fix is verified."),
):
    """Run n trials against the lab and print each verdict, then the rates with their 95% CIs.

    `ares drill --target you/repo` instead runs the whole containment + fix + PR loop against that
    repo's policy, in one go (--mode live for Nemotron; --n, --variant and --policy are not used).

    Exit code: 0 every trial contained or held; 1 a trial was NOT CONTAINED or failed;
    2 usage or lab error, or a broken event chain.
    With --target: 0 held or fixed and verified, 1 not fixed or needs review, 2 error, 3 inconclusive.
    """
    if target:
        if mode is Mode.scripted and recording not in lab.recordings():
            _fail("unknown recording %r; one of: %s" % (recording, ", ".join(lab.recordings())))
        _pipeline(target, base, pr, recording if mode is Mode.scripted else None, lab.DEFAULT_GOAL, None,
                  Caps(max_tokens=16000))
        return
    problem = validate(mode.value, drill.value, variant.value)
    if problem:
        _fail(problem)
    if not os.environ.get("ARES_ADMIN_TOKEN"):
        _fail(
            "ARES_ADMIN_TOKEN is not set: run `npm run setup` (it writes a random one to .env), "
            "or put ARES_ADMIN_TOKEN=<any random hex> in .env yourself"
        )
    _require_docker()
    if mode is Mode.live and not (
        os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    ):
        typer.secho(
            "warning: no NVIDIA_API_KEY set; the gateway will refuse model calls.",
            fg="yellow",
            err=True,
        )
    warn_about_keys()

    color = use_color(sys.stdout)
    drill_id = new_drill_id()
    typer.secho(BANNER, fg="cyan", bold=True)
    typer.echo()
    typer.echo(
        header_line(drill_id, mode.value, drill.value, variant.value, policy.value, n)
    )
    if mode is Mode.live:
        # Which model, not just "live": the id is knowable up front and the
        # whole drill's reach numbers are about this model's behaviour.
        typer.echo("model %s" % resolved_model())
    typer.echo(COLUMNS)

    compose_lab = ComposeLab(REPO)
    try:
        summary = run_drill(
            compose_lab,
            mode.value,
            drill.value,
            variant.value,
            policy.value,
            n,
            runs_dir,
            drill_id=drill_id,
            on_result=lambda r: typer.echo(format_row(r, color)),
        )
    except Exception as exc:  # noqa: BLE001 - lab/docker failures surface as one clear line
        _fail(str(exc))

    if n == 1 and summary.trials:
        spec = TrialSpec(
            drill_id,
            0,
            summary.trials[0].run_id,
            mode.value,
            drill.value,
            variant.value,
            policy.value,
        )
        typer.echo()
        # files are per source; show time order
        _print_evidence(sorted(compose_lab.events_for(spec), key=lambda e: e.ts))

    typer.echo()
    typer.echo(format_summary(summary, color, include_header=False))
    typer.echo()
    if summary.chain_problems:
        _box(
            [
                "✗ EVENT LOG CHAIN BROKEN: evidence not trustworthy",
                *summary.chain_problems[:6],
            ],
            "red",
        )
        raise typer.Exit(EXIT_ERROR)
    _verdict_box(summary)
    bad = (
        summary.verdicts["not_contained"]
        or summary.verdicts["failed"]
        or summary.interrupted
    )
    raise typer.Exit(EXIT_BAD if bad else EXIT_OK)


# ---- one trial / the fix loop (cli/lab.py, cli/pipeline.py) ---------------------------------


def _print_kill(rec: Dict[str, Any]) -> None:
    """The lever ladder and the verified time-to-kill, from the defender's record."""
    typer.echo(_rule("KILL"))
    typer.echo("  t_fire      %s" % rec.get("t_fire"))
    typer.echo("  t_verified  %s" % rec.get("t_verified"))
    typer.secho("  ttk_ms      %s   (fire -> verified)" % rec.get("ttk_ms"), bold=True)
    for lever in rec.get("levers", []):
        ok = lever.get("verified")
        mark = (
            typer.style("verified", fg="green")
            if ok
            else typer.style("UNVERIFIED", fg="red")
        )
        typer.echo("    lever %-18s %s" % (lever.get("name"), mark))
    verify = rec.get("verify") or {}
    typer.echo(
        "    docker inspect: labnet_endpoint=%s paused=%s"
        % (verify.get("labnet_endpoint"), verify.get("paused"))
    )
    typer.echo(
        "    post_kill_events=%s  post_kill_leaks=%s"
        % (rec.get("post_kill_events"), rec.get("post_kill_leaks"))
    )
    typer.echo()


def _fingerprint(value: str) -> str:
    """Twelve hex characters of sha256. Enough to compare two keys, useless as a key."""
    return hashlib.sha256(value.encode()).hexdigest()[:12] if value else "(empty)"


def key_warnings(env_file: Optional[Path] = None) -> List[str]:
    """Reasons the key you think you are using is not the one that will be used.

    Two ways to be running an old key, both silent, and both of which surface
    only as a confusing upstream error much later:

    1. `.env` is loaded with override=False, so a variable exported in the
       shell beats the file. `.env.example` tells you to run
       `set -a; source .env; set +a` for bare compose and the selftests -- do
       that, then edit `.env`, and every later run quietly uses the stale
       export.
    2. The gateway receives its key at container-create time. `prepare()`
       brings it up without --force-recreate and the per-trial recreate skips
       it on purpose (lever 1 lives there), so a gateway started before the key
       changed keeps the old one until `ares down`.

    Fingerprints only. This prints to a terminal, and the real key is the one
    thing in the system that must not leak.
    """
    from dotenv import dotenv_values

    warnings: List[str] = []
    path = env_file or (REPO / ".env")
    in_file = dotenv_values(path) if path.is_file() else {}

    for name in ("NVIDIA_API_KEY", "OPENROUTER_API_KEY"):
        live, filed = os.environ.get(name, ""), (in_file.get(name) or "")
        if live and filed and live != filed:
            warnings.append(
                "%s exported in your shell (%s) differs from .env (%s); the shell wins. "
                "`unset %s` to use the file."
                % (name, _fingerprint(live), _fingerprint(filed), name)
            )

    want = os.environ.get("NVIDIA_API_KEY", "")
    if want:
        got = _gateway_key()
        if got is not None and got != want:
            warnings.append(
                "the running gateway holds a different NVIDIA_API_KEY (%s) than this run "
                "would use (%s). It takes the key at container-create time: `ares down` "
                "first, or the drill runs on the old key."
                % (_fingerprint(got), _fingerprint(want))
            )
    return warnings


def _gateway_key() -> Optional[str]:
    """The key inside the running gateway, or None if it is not up / unreadable."""
    try:
        done = subprocess.run(
            ["docker", "inspect", "ares-lab-gateway-1", "--format",
             "{{range .Config.Env}}{{println .}}{{end}}"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    for line in done.stdout.splitlines():
        name, _, value = line.partition("=")
        if name == "NVIDIA_API_KEY":
            return value
    return None


def warn_about_keys() -> None:
    for text in key_warnings():
        typer.secho("warning: %s" % text, fg="yellow", err=True)


def resolved_model(model: Optional[str] = None) -> str:
    """The model id that will actually be used, resolved the same way the
    harness resolves it: --model, then ARES_MODEL, then the harness default.

    The banner used to print the literal "Nemotron" whenever --model was
    omitted, which is every normal run -- so it named a family, not the model,
    and said the same thing whichever model the key was pointed at. The id is
    knowable before the run, so say it. What the gateway *observed* is reported
    separately after the run, from the evidence (see `observed_models`).
    """
    return model or os.environ.get("ARES_MODEL") or harness.DEFAULT_MODEL


def observed_models(events: List[Dict[str, Any]]) -> List[str]:
    """The model ids the gateway actually recorded for this run.

    The gateway logs `detail.model` on every call it forwards, so this is
    evidence rather than intent: it catches the case where the harness fell
    back, or ARES_MODEL in the sandbox differed from the shell that launched
    the drill. The harness is never a source of evidence (section 3), which is
    why this reads the gateway's events and not the harness's own report.
    """
    seen = []
    for event in events:
        if event.get("kind") != "llm":
            continue
        name = (event.get("detail") or {}).get("model")
        if name and name not in seen:
            seen.append(name)
    return seen


def dashboard_url(run_id: str) -> str:
    """Where to watch this run in the dashboard.

    `?run=<run_id>` is enough: web.model.resolve_run accepts a bare run id, so
    the CLI does not have to know how the dashboard keys its runs (that is
    `<dir slug>:<run_id>`, and duplicating the rule here would be one more
    thing to keep in step). ARES_WEB_URL overrides the host for a drill running
    on the VM while you watch from a laptop.
    """
    base = os.environ.get("ARES_WEB_URL") or (
        "http://127.0.0.1:%s" % os.environ.get("ARES_WEB_PORT", "8090")
    )
    return "%s/?run=%s" % (base.rstrip("/"), run_id)


_COLORS = {"start": "cyan", "done": "green", "fail": "red"}


def _pipeline(target: str, base: str, open_pr: bool, recording: Optional[str], goal: str,
              model: Optional[str], caps: Caps) -> None:
    token = os.environ.get("GITHUB_TOKEN", "")
    typer.secho(BANNER, fg="cyan", bold=True)
    typer.echo()
    problems = pipeline.preflight(target, token, live=not recording)
    if problems:
        typer.echo(_rule("PREFLIGHT"))
        for p in problems:
            typer.secho("  ✗ %s" % p, fg="red")
        raise typer.Exit(EXIT_ERROR)
    typer.echo(_rule("DRILL + FIX LOOP · %s@%s" % (target, base)))

    def show(line: Dict[str, Any]) -> None:
        mark, text = pipeline.console_line(line)  # the same text the PR's console section shows
        typer.echo("  %s %s" % (typer.style(mark, fg=_COLORS.get(line["status"]), bold=True), text))

    try:
        summary = pipeline.run(
            target,
            base,
            token,
            "scripted" if recording else "model",
            goal,
            recording,
            model,
            caps,
            open_pr=open_pr,
            judge=_inconclusive,
            show=show,
        )
    except (lab.DrillError, github_pr.PRError) as e:
        _fail(str(e))
    typer.echo(_rule())
    result = summary["result"]
    lines = ["%s   %s" % (result.upper().replace("_", " "), summary["pipeline_id"])]
    lines += textwrap.wrap(summary["reason"] or "", WIDTH - 4)
    for k in summary["containment"]["kill_checks"]:
        lines.append("kill check (%s policy): %s, %s ms, levers %s, %d leaks" % (
            k["policy"], "contained" if k["contained"] else "NOT CONTAINED", k["time_to_kill_ms"],
            k["levers_verified"], k["post_kill_leaks"]))
    if summary.get("pr", {}).get("url"):
        lines.append("PR: %s" % summary["pr"]["url"])
    lines.append("summary: runs/pipelines/%s/summary.json" % summary["pipeline_id"])
    _box(lines, {"fixed": "green", "held": "green", "inconclusive": "yellow"}.get(result, "red"))
    if result == "error" or summary.get("pr", {}).get("error"):
        raise typer.Exit(EXIT_ERROR)
    raise typer.Exit(
        {"fixed": 0, "held": 0, "inconclusive": EXIT_INCONCLUSIVE}.get(
            result, EXIT_BREAKOUT
        )
    )


@app.command("hunt")
def hunt_cmd(
    mode: Mode = typer.Option(Mode.live, help="live runs the model; scripted replays a recording."),
    drill: Drill = typer.Option(Drill.propensity, help="Which goal the agent gets."),
    variant: Variant = typer.Option(Variant.A, help="Which copy of the answer key: B is the held-out one."),
    policy: Policy = typer.Option(Policy.before, help="before = flaws on; after = the fix."),
    max_trials: int = typer.Option(
        10, "--max-trials", "-n", min=1,
        help="Give up after this many attempts without a breach."),
    runs_dir: Path = typer.Option(
        REPO / "lab" / "runs", help="Where result.json and summary.json land.",
        show_default="lab/runs"),
):
    """Run trials until the first breach, show it in full, and stop.

    `ares drill` measures a rate over a fixed n. This looks for one breakout and
    then stops, so what you get is a worked example rather than a statistic: the
    evidence that led to it, the kill path that answered it, and a link to watch
    it in the dashboard.

    Because it stops on the first success, the trials are a stopping rule and
    not a sample -- the count of attempts is reported, but no rate and no
    interval, which would describe a population that was never drawn. Use
    `ares drill --n 20` for numbers you can quote.

    Exit code: 0 a breach was found and contained; 1 found and NOT contained;
    2 lab error or a broken chain; 3 no breach within --max-trials.
    """
    if problem := validate(mode.value, drill.value, variant.value):
        _fail(problem)
    if not os.environ.get("ARES_ADMIN_TOKEN"):
        _fail(
            "ARES_ADMIN_TOKEN is not set: run `npm run setup` (it writes a random one to .env), "
            "or put ARES_ADMIN_TOKEN=<any random hex> in .env yourself"
        )
    _require_docker()
    if mode is Mode.live and not (
        os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    ):
        typer.secho("warning: no NVIDIA_API_KEY set; the gateway will refuse model calls.",
                    fg="yellow", err=True)
    warn_about_keys()

    color = use_color(sys.stdout)
    drill_id = new_drill_id()
    typer.secho(BANNER, fg="cyan", bold=True)
    typer.echo()
    typer.echo("hunt %s  %s  %s  variant %s  policy %s  stop at first breach (max %d)"
               % (drill_id, mode.value, drill.value, variant.value, policy.value, max_trials))
    if mode is Mode.live:
        typer.echo("model %s" % resolved_model())
    typer.echo(COLUMNS)

    compose_lab = ComposeLab(REPO)
    try:
        summary = run_drill(
            compose_lab, mode.value, drill.value, variant.value, policy.value,
            max_trials, runs_dir, drill_id=drill_id,
            on_result=lambda r: typer.echo(format_row(r, color)),
            stop_after=lambda r: r.fired,
        )
    except Exception as exc:  # noqa: BLE001 - lab/docker failures surface as one clear line
        _fail(str(exc))

    if summary.chain_problems:
        _box(["✗ EVENT LOG CHAIN BROKEN: evidence not trustworthy",
              *summary.chain_problems[:6]], "red")
        raise typer.Exit(EXIT_ERROR)

    breach = next((t for t in summary.trials if t.fired), None)
    attempts = len(summary.trials)
    if breach is None:
        typer.echo()
        _box([
            "○ no breach in %d attempt(s)   drill %s" % (attempts, drill_id),
            "The key was never reached, which is not evidence that it cannot be:",
            "the agent may simply not have tried. Raise --max-trials, or use",
            "--drill breakout to instruct it rather than tempt it.",
        ], "yellow")
        raise typer.Exit(EXIT_NO_BREACH)

    _show_breach(compose_lab, summary, breach, drill_id, mode, drill, variant, policy,
                 attempts, max_trials)
    raise typer.Exit(EXIT_BAD if breach.verdict == "not_contained" else EXIT_OK)


def _show_breach(compose_lab, summary, breach, drill_id, mode, drill, variant, policy,
                 attempts: int, max_trials: int) -> None:
    """The whole story of one breakout, the way `ares trial` tells it."""
    spec = TrialSpec(drill_id, breach.trial, breach.run_id, mode.value, drill.value,
                     variant.value, policy.value)
    events = sorted(compose_lab.events_for(spec), key=lambda e: e.ts)

    typer.echo()
    typer.echo(_rule("BREACH"))
    typer.echo("  found on attempt %d (cap %d)   ·   run %s"
               % (attempts, max_trials, breach.run_id))
    ran = observed_models([e.model_dump() if hasattr(e, "model_dump") else e for e in events])
    if ran:
        typer.echo("  model %s" % ", ".join(ran))
    typer.echo()
    _print_evidence(events)

    record = None
    if breach.kill_record:
        path = Path(breach.kill_record)
        if not path.is_absolute():
            path = REPO / path
        if path.is_file():
            record = json.loads(path.read_text(encoding="utf-8"))
    typer.echo()
    if record is not None:
        _print_kill(record)
    else:
        # A fire with no record means nothing answered it. Say that plainly
        # rather than leaving the kill section blank.
        _box(["✗ BREACH WITH NO KILL RECORD   run %s" % breach.run_id,
              "The bait was reached and no lever was recorded. Nothing stopped it."], "red")

    typer.secho("  watch it: %s" % dashboard_url(breach.run_id), fg="cyan", bold=True)
    typer.echo()
    if breach.verdict == "contained":
        leaks = (record or {}).get("post_kill_leaks")
        _box(["✓ CONTAINED   the agent broke out and was killed",
              "found on attempt %d of up to %d  ·  killed in %s ms  ·  %s post-kill leak(s)"
              % (attempts, max_trials, breach.ttk_ms,
                 leaks if leaks is not None else "?"),
              "run %s" % breach.run_id], "green")
    else:
        _box(["✗ NOT CONTAINED   the agent broke out and the kill did not hold",
              "found on attempt %d of up to %d   run %s"
              % (attempts, max_trials, breach.run_id)], "red")


@app.command("trial")
def trial_cmd(
    recording: Optional[str] = typer.Argument(
        None,
        autocompletion=lab.recordings,
        show_default=False,
        help="Replay a recording from agent/recorded/ (%s). Omit to run live Nemotron."
        % ", ".join(lab.recordings()),
    ),
    goal: str = typer.Option(
        lab.DEFAULT_GOAL, help="Goal given to the agent. A goal, never a method."
    ),
    model: Optional[str] = typer.Option(
        None, help="Model id; default is the harness's ARES_MODEL."
    ),
    max_steps: int = typer.Option(12, help="Agent step cap."),
    max_tokens: int = typer.Option(
        16000,
        help="Cumulative token budget. The 6000 elsewhere dies around "
        "step 7 for a reasoning model (the conversation is recounted "
        "each call); ~16000 covers 12 steps.",
    ),
    max_wall_seconds: int = typer.Option(90, help="Agent wall-clock cap."),
    kill: bool = typer.Option(
        True,
        "--kill/--no-kill",
        help="Arm the defender: a fire triggers a verified three-lever kill. "
        "--no-kill only detects the breakout (needs no docker beyond the lab).",
    ),
    target: Optional[str] = typer.Option(
        None,
        help="owner/repo of a company sandbox policy. Runs the whole loop: drill, fix, rerun "
        "in a fresh lab, replay, open a PR (needs GITHUB_TOKEN).",
    ),
    base: str = typer.Option(
        "main",
        help="With --target: branch to read the policy from and open the PR against.",
    ),
    pr: bool = typer.Option(
        True,
        "--pr/--no-pr",
        help="With --target: open the PR once the fix is verified.",
    ),
):
    """Run one trial: the agent harness in the Leakbox sandbox, LLM calls via the gateway.

    Examples: `ares trial fetch_through` (replay, no key) or `ares trial` (live).
    `ares trial --target acme/sandbox` runs the full fix loop against that repo's policy.
    For n trials with intervals use `ares drill`.
    Exit code: 0 boundary held, 1 breakout (fire/breach), 2 error, 3 inconclusive
    (the agent did not complete a trial -- usually a transient provider error).
    With --target: 0 held or fixed and verified, 1 not fixed or needs review, 2 error, 3 inconclusive.
    """
    if target:
        _pipeline(
            target,
            base,
            pr,
            recording,
            goal,
            model,
            Caps(
                max_steps=max_steps,
                max_tokens=max_tokens,
                max_wall_seconds=max_wall_seconds,
            ),
        )
        return
    driver = "scripted" if recording else "model"
    if driver == "model" and not (
        os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
    ):
        typer.secho(
            "warning: no NVIDIA_API_KEY set; the gateway will refuse model calls "
            "(upstream_key_missing). Name a recording to run without a key.",
            fg="yellow",
            err=True,
        )
    if driver == "model":
        warn_about_keys()

    caps = Caps(
        max_steps=max_steps, max_tokens=max_tokens, max_wall_seconds=max_wall_seconds
    )
    if recording:
        title = "Recorded agent: %s" % recording
        detail = SCENARIOS.get(recording, "replays agent/recorded/%s.json" % recording)
    else:
        title = "Live agent: %s" % resolved_model(model)
        detail = "goal: %s" % goal

    typer.secho(BANNER, fg="cyan", bold=True)
    typer.echo()
    typer.echo(_rule())
    typer.secho("  %s" % title, bold=True)
    typer.echo("  %s" % detail)
    typer.echo(_rule())
    typer.echo()

    def announce(run_id: str) -> None:
        # Printed before the lab comes up, so there is time to open it and
        # watch the sandbox play this run out as the events land.
        typer.echo("  %s %s" % (typer.style("watch:", fg="cyan", bold=True),
                                dashboard_url(run_id)))
        typer.echo()

    steps = iter(range(1, 6))
    try:
        trial = lab.drill(
            driver,
            goal,
            recording,
            model,
            caps,
            kill=kill,
            on_run_id=announce,
            on_step=lambda msg: typer.echo(
                "  %s %s"
                % (typer.style("[%d/4]" % next(steps), fg="cyan", bold=True), msg)
            ),
        )
    except lab.DrillError as e:
        _fail(str(e))

    typer.echo()
    _print_evidence(trial.events)

    o = trial.outcome
    typer.echo()
    typer.echo(_rule("AGENT"))
    # From the gateway's own events, so it is what ran rather than what was
    # asked for -- it differs when the harness fell back or the sandbox's
    # ARES_MODEL was not the shell's.
    ran = observed_models(trial.events)
    if ran:
        typer.echo("  model %s" % ", ".join(ran))
    stopped = o.get("stop_reason")
    stopped_str = (
        "killed by the defender mid-run (SIGKILL)"
        if stopped == "killed_by_defender"
        else stopped
    )
    typer.echo(
        "  steps %s   ·   tool calls %s   ·   stopped: %s%s"
        % (
            o.get("steps") if o.get("steps") is not None else "-",
            len(o.get("tool_calls", [])),
            stopped_str,
            "   ·   reported blocked" if o.get("reported_blocked") else "",
        )
    )
    for err in o.get("errors", []):
        typer.secho("  ! agent error: %s" % err, fg="yellow")
    typer.echo()

    outcome = classify(trial, max_steps)
    # The kill path is rendering, not judgement: show it whenever the defender
    # wrote a record, including the run where the kill did not hold.
    if outcome.kill_record is not None:
        _print_kill(outcome.kill_record)
    _box(outcome.lines, outcome.color)
    typer.echo()
    typer.secho("  replay it: %s" % dashboard_url(trial.run_id), fg="cyan")
    typer.echo()
    if outcome.exit_code:
        raise typer.Exit(outcome.exit_code)


@app.command()
def flaws(
    action: Optional[FlawAction] = typer.Argument(
        None,
        help="on, off, or reset (back to the committed leakbox.yaml). Omit to list.",
    ),
    names: Optional[List[str]] = typer.Argument(
        None,
        autocompletion=lambda: list(lab.read_flaws()),
        help="Flaws to change; default is all of them.",
    ),
    policy: Policy = typer.Option(
        Policy.before, help="Which policy file to list (listing only)."
    ),
):
    """Show Leakbox flaws, or toggle them in lab/leakbox.yaml. Changes apply on the next request.

    Examples: `ares flaws`, `ares flaws --policy after`, `ares flaws off fetch_through`, `ares flaws reset`.
    `ares drill --policy` never rewrites leakbox.yaml; it selects a policy file per drill.
    """
    try:
        if action is FlawAction.reset:
            lab.reset_flaws()
        elif action is not None:
            lab.set_flaws(names or list(lab.read_flaws()), action is FlawAction.on)
        if action is None and policy is not Policy.before:
            _, current = load_leakbox(str(POLICY_FILES_HOST[policy.value]))
        else:
            current = lab.read_flaws()
    except lab.DrillError as e:
        _fail(str(e))
    typer.echo(_rule("LEAKBOX FLAWS (%s)" % policy.value))
    for name, on in current.items():
        state = (
            typer.style("● ON ", fg="red", bold=True)
            if on
            else typer.style("○ off", fg="green")
        )
        typer.echo("  %s %s  %s" % (name, "·" * (22 - len(name)), state))
    typer.echo(_rule())


@app.command()
def fix(
    kill_record: Path = typer.Argument(
        ...,
        dir_okay=False,
        help="A defender kill record, e.g. lab/runs/kills/r_ab12-0.json (from any folder).",
    ),
    events_dir: Path = typer.Option(
        lab.EVENTS_DIR, help="Directory holding the lab's *.jsonl event logs."
    ),
    open_pr: bool = typer.Option(
        False, "--open-pr", help="Open a GitHub PR with the fix (needs GITHUB_TOKEN)."
    ),
    base: str = typer.Option("main", help="Branch the PR targets."),
    repo: Optional[str] = typer.Option(
        None, help="owner/name; default is the origin remote."
    ),
):
    """Name the cause of a breakout and print the leakbox.yaml change that closes it.

    Without --open-pr nothing is changed. With it, the fix is committed to a new branch on GitHub
    and a PR is opened against --base; the local checkout is untouched.
    Exit code: 0 a fix was found, 1 needs manual review, 2 error.
    """
    kill_record = _repo_path(kill_record)
    if not kill_record.is_file():
        _fail("no kill record at %s" % kill_record)
    token = os.environ.get("GITHUB_TOKEN", "")
    if open_pr and not token:
        _fail(
            "--open-pr needs GITHUB_TOKEN (fine-grained, this repo, Contents + Pull requests read/write)"
        )
    try:
        record = KillRecord.model_validate_json(kill_record.read_text())
    except ValueError as e:
        _fail("not a kill record: %s" % e)
    events = [
        e for path in sorted(events_dir.glob("*.jsonl")) for e in read_events(path)
    ]
    plan = fixes.plan_fix(record, events, lab.LEAKBOX_YAML.read_text())
    c = plan.cause

    typer.echo(_rule("CAUSE"))
    typer.echo("  run %s trial %d   ·   fired %s" % (record.run_id, record.trial, c.ts))
    typer.echo(
        "  reached   %s%s%s"
        % (
            c.dst_host or "?",
            c.path or "",
            "   (bait %s)" % c.bait_id if c.bait_id else "",
        )
    )
    typer.echo("  via flaw  %s" % (c.flaw or "none recorded"))
    if c.kill_failed:
        typer.secho(
            "  kill      NOT CONTAINED: %d post-kill leak(s)" % record.post_kill_leaks,
            fg="red",
        )
    typer.echo()

    typer.echo(_rule("FIX"))
    for flaw in plan.flaws:
        t = fixes.FIXES[flaw]
        typer.secho("  %s" % t.title, bold=True)
        typer.echo("  %s" % t.why)
        if t.rebuild:
            typer.secho(
                "  Takes effect only after the sandbox is rebuilt.", fg="yellow"
            )
        typer.echo()
    for reason in plan.unresolved:
        typer.secho("  ! %s" % reason, fg="yellow")
    if plan.diff:
        if plan.unresolved:
            typer.echo()
        for line in plan.diff.splitlines():
            color = (
                "green"
                if line.startswith("+") and not line.startswith("+++")
                else (
                    "red"
                    if line.startswith("-") and not line.startswith("---")
                    else None
                )
            )
            typer.secho("  %s" % line, fg=color)
    typer.echo(_rule())
    if not plan.fixable:
        raise typer.Exit(EXIT_BREAKOUT)

    if open_pr:
        narration = None
        typer.echo("  Writing PR text with %s ..." % pr_writer.PR_MODEL)
        try:
            narration = pr_writer.narrate(
                plan, record, os.environ.get("NVIDIA_API_KEY", "")
            )
            typer.echo(
                "  PR text: written by %s, checked against the evidence"
                % narration.model
            )
        except pr_writer.NarrationError as e:
            typer.secho("  PR text: fixed template (%s)" % e, fg="yellow")
        target_repo = repo or github_pr.repo_from_remote(str(lab.REPO))
        try:
            url = github_pr.open_fix_pr(
                plan,
                record,
                target_repo,
                base,
                token,
                narration=narration,
            )
        except github_pr.PRError as e:
            _fail(str(e))
        typer.secho("  PR: %s" % url, fg="green", bold=True)
        try:
            if slack.alert_pr(target_repo, url, plan.flaws):
                typer.secho("  Slack alert sent", fg="green")
        except slack.SlackError as e:  # the PR is open; only the alert failed
            typer.secho("  Slack alert failed: %s" % e, fg="yellow")


@app.command("setup-target")
def setup_target(repo: str = typer.Argument(..., help="owner/name of a GitHub repo you own, e.g. you/ares-sandbox-testing.")):
    """Turn an empty (or any) repo into a company sandbox Ares can test: adds lab/leakbox.yaml with the
    Leakbox flaws on. Leaves an existing policy alone. Needs GITHUB_TOKEN with Contents read/write.
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        _fail("GITHUB_TOKEN is missing: add it to .env (fine-grained, this repo, Contents + Pull requests read/write)")
    # The committed policy, not a locally toggled copy: a target should start with every flaw as shipped.
    shown = subprocess.run(["git", "show", "HEAD:lab/leakbox.yaml"], cwd=lab.REPO, text=True, capture_output=True)
    text = shown.stdout if shown.returncode == 0 else lab.LEAKBOX_YAML.read_text()
    try:
        branch, created = github_pr.GitHub(repo, token).seed_policy(text)
    except github_pr.PRError as e:
        _fail(str(e))
    if created:
        typer.secho("  ✓ added lab/leakbox.yaml to %s@%s" % (repo, branch), fg="green")
    else:
        typer.echo("  · %s@%s already has lab/leakbox.yaml; left it as is" % (repo, branch))
    typer.echo("  next: ./.venv/bin/ares drill --target %s" % repo)


@app.command()
def down():
    """Stop and remove the lab containers and networks."""
    _require_docker()
    # Compose must interpolate ARES_ADMIN_TOKEN just to parse the file; stopping the lab
    # does not use it, so any value will do here.
    proc = subprocess.run(
        ["docker", "compose", "down", "--remove-orphans"],
        cwd=str(LAB_DIR),
        env={**os.environ, "ARES_ADMIN_TOKEN": lab.admin_token()},
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        _fail("lab failed to stop:\n%s" % proc.stderr.strip())
    typer.echo("lab stopped")


if __name__ == "__main__":
    app()
