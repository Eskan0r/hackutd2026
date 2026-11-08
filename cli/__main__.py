"""`python -m cli drill ...`: run n trials against the lab and print the verdicts.

    ./.venv/bin/python -m cli drill --mode scripted --drill breakout --variant A --policy before --n 20
    ./.venv/bin/python -m cli drill --mode scripted --drill breakout --variant B --policy after --n 20
    ./.venv/bin/python -m cli drill --mode scripted --drill normal --policy after --n 1

Needs Docker and the same ARES_ADMIN_TOKEN the lab runs with. Only `drill` exists;
the other ARCHITECTURE.md section 6 subcommands are roadmap.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from cli.drill import (
    REPO,
    COLUMNS,
    ComposeLab,
    format_row,
    format_summary,
    header_line,
    new_drill_id,
    run_drill,
    use_color,
)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drill", help="run n trials and score them")
    d.add_argument("--mode", choices=["scripted", "live"], default="scripted")
    d.add_argument(
        "--drill", choices=["breakout", "normal", "propensity"], default="breakout"
    )
    d.add_argument("--variant", choices=["A", "B"], default="A")
    d.add_argument("--policy", choices=["before", "after"], default="before")
    d.add_argument("--n", type=int, default=20)
    d.add_argument("--runs-dir", default="lab/runs")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if not os.environ.get("ARES_ADMIN_TOKEN"):
        print(
            "export ARES_ADMIN_TOKEN=$(openssl rand -hex 16) first (same value the lab runs with)",
            file=sys.stderr,
        )
        return 2
    color = use_color(sys.stdout)
    drill_id = new_drill_id()
    print(
        header_line(drill_id, args.mode, args.drill, args.variant, args.policy, args.n)
    )
    print(COLUMNS)
    summary = run_drill(
        ComposeLab(REPO),
        args.mode,
        args.drill,
        args.variant,
        args.policy,
        args.n,
        Path(args.runs_dir),
        drill_id=drill_id,
        on_result=lambda r: print(format_row(r, color), flush=True),
    )
    print()
    print(format_summary(summary, color, include_header=False))
    bad = summary.verdicts["not_contained"] or summary.verdicts["failed"]
    return 1 if bad or summary.interrupted else 0


if __name__ == "__main__":
    sys.exit(main())
