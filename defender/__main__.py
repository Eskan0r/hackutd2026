# Stopgap entry point until the `ares` CLI exists.
#   python -m defender selftest
#   python -m defender watch --run-id r_local [--trial 0] [--soft-kill]
# `watch` needs the lab up and the run registered with the gateway (admin API on 127.0.0.1:8081,
# token from ARES_ADMIN_TOKEN, compose default "ares-lab-admin").

import argparse
import sys

from ares.contracts import Run
from ares.levers import find_sandbox
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
    w.add_argument("--soft-kill", action="store_true")
    args = p.parse_args()

    if args.cmd == "selftest":
        return selftest.main()

    run = Run(run_id=args.run_id, trial=args.trial, container=find_sandbox(), events_dir=args.events_dir)
    print("watching %s for run %s trial %d ..." % (args.events_dir, run.run_id, run.trial))
    rec = watch_and_kill(run, args.kills_dir, soft_kill=args.soft_kill)
    print(rec.model_dump_json(indent=2))
    return 0 if rec.contained else 1


if __name__ == "__main__":
    sys.exit(main())
