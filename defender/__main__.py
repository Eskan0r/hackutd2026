# Stopgap entry point until the `ares` CLI exists.
#   python -m defender selftest
#   python -m defender watch --run-id r_local [--trial 0] [--soft-kill]

import argparse
import sys

from ares.levers import Run, find_sandbox
from defender import selftest
from defender.watch import watch_and_kill


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m defender")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    w = sub.add_parser("watch")
    w.add_argument("--run-id", required=True)
    w.add_argument("--trial", type=int, default=0)
    w.add_argument("--events-dir", default="lab/runs")
    w.add_argument("--kills-dir", default="lab/runs/kills")
    w.add_argument("--deny-dir", default="lab/runs/deny")
    w.add_argument("--soft-kill", action="store_true")
    args = p.parse_args()

    if args.cmd == "selftest":
        return selftest.main()

    run = Run(args.run_id, args.trial, find_sandbox(), args.deny_dir)
    print(f"watching {args.events_dir} for run {run.run_id} trial {run.trial} ...")
    rec = watch_and_kill(run, args.events_dir, args.kills_dir, soft_kill=args.soft_kill)
    print(rec.model_dump_json(indent=2))
    return 0 if rec.contained else 1


if __name__ == "__main__":
    sys.exit(main())
