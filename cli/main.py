"""`ares` command line: a Typer layer over cli/drill.py. Parse, call, print.

    ares drill --variant A --policy before --n 20
    ares drill --variant B --policy after  --n 20
    ares drill --drill normal --policy after --n 1
    ares flaws [--policy after]
    ares down

Every verdict comes from cli/drill.py, which decides from the lab's events and the
defender's kill record only. This file never looks at what the agent said.
"""

from __future__ import annotations

import os
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import List, Optional

import typer

from ares.contracts import Event
from ares.results import DrillSummary
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

app = typer.Typer(no_args_is_help=True, help="Ares: a fire drill for AI agent containment.")

EXIT_OK, EXIT_BAD, EXIT_ERROR = 0, 1, 2
WIDTH = 78
BANNER = "   ▄▀█ █▀█ █▀▀ █▀\n   █▀█ █▀▄ ██▄ ▄█\n   your sandbox defender"


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
        return "no scripted recording for %s/%s; use --mode live or one of: %s" % (drill, variant, known)
    return None


def _fail(message: str) -> None:
    typer.secho("error: %s" % message, fg="red", err=True)
    raise typer.Exit(EXIT_ERROR)


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
    label, color = _SEVERITY.get(e.severity, (e.severity, None))
    target = _printable("%s%s" % (e.dst_host or "", e.path or ""))
    lines = [
        "  %s  %s  %-14s %-9s %s"
        % (e.ts[11:23], typer.style(label, fg=color, bold=color is not None), e.source, e.kind, target)
    ]
    extra = "   ".join("%s=%s" % (k, v) for k, v in (("flaw", e.flaw), ("bait_id", e.bait_id)) if v)
    decision = (e.detail or {}).get("decision")
    if decision:
        extra = ("%s   " % extra if extra else "") + "decision=%s" % _printable(str(decision))
    if extra:
        lines.append(typer.style("%s└─ %s" % (" " * 24, extra), fg=color))
    return lines


def _verdict_box(s: DrillSummary) -> None:
    v = s.verdicts
    tag = "   drill %s" % s.drill_id
    if v["not_contained"] or v["failed"]:
        _box(["✗ %d NOT CONTAINED · %d failed%s" % (v["not_contained"], v["failed"], tag)], "red")
    elif s.drill == "breakout" and v["not_exercised"]:
        _box(["○ %d/%d not exercised: the key was never tried, which proves nothing%s"
              % (v["not_exercised"], s.n, tag)], "yellow")
    elif s.drill == "normal":
        k = s.allowed_task_passed.k if s.allowed_task_passed else 0
        _box(["✓ normal work still succeeds %d/%d%s" % (k, s.n, tag)], "green" if k == s.n else "yellow")
    else:
        _box(["✓ %d reached & killed · %d refused · 0 got through%s" % (v["contained"], v["held"], tag)], "green")


@app.command("drill")
def drill_cmd(
    mode: Mode = typer.Option(Mode.scripted, help="scripted replays a recording; live runs Nemotron."),
    drill: Drill = typer.Option(Drill.breakout, help="Which goal the agent gets."),
    variant: Variant = typer.Option(Variant.A, help="Which copy of the answer key: B is the held-out one."),
    policy: Policy = typer.Option(Policy.before, help="before = flaws on; after = the fix."),
    n: int = typer.Option(20, min=1, help="Trials. Each gets fresh containers and a fresh run id."),
    runs_dir: Path = typer.Option(Path("lab/runs"), help="Where result.json and summary.json land."),
):
    """Run n trials against the lab and print each verdict, then the rates with their 95% CIs.

    Exit code: 0 every trial contained or held; 1 a trial was NOT CONTAINED or failed;
    2 usage or lab error, or a broken event chain.
    """
    problem = validate(mode.value, drill.value, variant.value)
    if problem:
        _fail(problem)
    if not os.environ.get("ARES_ADMIN_TOKEN"):
        _fail("export ARES_ADMIN_TOKEN=$(openssl rand -hex 16) first (same value the lab runs with)")
    if mode is Mode.live and not (os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        typer.secho("warning: no NVIDIA_API_KEY set; the gateway will refuse model calls.", fg="yellow", err=True)

    color = use_color(sys.stdout)
    drill_id = new_drill_id()
    typer.secho(BANNER, fg="cyan", bold=True)
    typer.echo()
    typer.echo(header_line(drill_id, mode.value, drill.value, variant.value, policy.value, n))
    typer.echo(COLUMNS)

    lab = ComposeLab(REPO)
    try:
        summary = run_drill(
            lab, mode.value, drill.value, variant.value, policy.value, n, runs_dir,
            drill_id=drill_id, on_result=lambda r: typer.echo(format_row(r, color)),
        )
    except Exception as exc:  # noqa: BLE001 - lab/docker failures surface as one clear line
        _fail(str(exc))

    if n == 1 and summary.trials:
        spec = TrialSpec(drill_id, 0, summary.trials[0].run_id, mode.value, drill.value, variant.value, policy.value)
        typer.echo()
        typer.echo(_rule("EVIDENCE"))
        typer.secho("  %-12s  %-6s  %-14s %-9s %s" % ("TIME (UTC)", "SEV", "SOURCE", "KIND", "TARGET"), dim=True)
        events = sorted(lab.events_for(spec), key=lambda e: e.ts)  # files are per source; show time order
        for e in events:
            for line in _event_lines(e):
                typer.echo(line)
        if not events:
            typer.echo("  (no events for this run)")

    typer.echo()
    typer.echo(format_summary(summary, color, include_header=False))
    typer.echo()
    if summary.chain_problems:
        _box(["✗ EVENT LOG CHAIN BROKEN: evidence not trustworthy", *summary.chain_problems[:6]], "red")
        raise typer.Exit(EXIT_ERROR)
    _verdict_box(summary)
    bad = summary.verdicts["not_contained"] or summary.verdicts["failed"] or summary.interrupted
    raise typer.Exit(EXIT_BAD if bad else EXIT_OK)


@app.command()
def flaws(policy: Policy = typer.Option(Policy.before, help="Which policy file to show.")):
    """List the Leakbox flaws a policy leaves on. Read-only: the policy is chosen per drill
    with `ares drill --policy`, never by rewriting leakbox.yaml."""
    _, current = load_leakbox(str(POLICY_FILES_HOST[policy.value]))
    typer.echo(_rule("LEAKBOX FLAWS (%s)" % policy.value))
    for name, on in current.items():
        state = typer.style("● ON ", fg="red", bold=True) if on else typer.style("○ off", fg="green")
        typer.echo("  %s %s  %s" % (name, "·" * (22 - len(name)), state))
    typer.echo(_rule())


@app.command()
def down():
    """Stop and remove the lab containers and networks."""
    if not os.environ.get("ARES_ADMIN_TOKEN"):
        _fail("compose needs ARES_ADMIN_TOKEN set, even to stop the lab")
    proc = subprocess.run(
        ["docker", "compose", "down", "--remove-orphans"],
        cwd=str(LAB_DIR), env=dict(os.environ), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        _fail("lab failed to stop:\n%s" % proc.stderr.strip())
    typer.echo("lab stopped")


if __name__ == "__main__":
    app()
