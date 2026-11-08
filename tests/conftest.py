"""Shared test doubles. No Docker anywhere in the suite."""

from __future__ import annotations

from ares.events import EventWriter, verify_chain
from cli.drill import read_trial_events


class StubLab:
    """Stands in for ComposeLab: writes the events a trial would leave behind (as real
    hash-chained lines) and hands back a prebuilt kill record."""

    def __init__(self, events_dir, events, kill=None, rc=0):
        self.events_dir, self.events, self.kill, self.rc = events_dir, events, kill, rc
        self.calls = []

    def prepare(self):
        self.calls.append("prepare")

    def register_run(self, spec, dummy_key):
        self.calls.append(("register", spec.run_id, dummy_key))
        self._run_id, self._trial = spec.run_id, spec.trial  # stamp this trial's events

    def up(self, spec, env):
        self.calls.append(("up", env))

    def start_watch(self, spec):
        self.calls.append("watch")

    def exec_harness(self, argv, timeout_s):
        self.calls.append(("exec", argv))
        for e in self.events:
            EventWriter(self.events_dir, "proxy").emit(
                e.source, e.kind, e.severity,
                run_id=self._run_id, trial=self._trial, dst_host=e.dst_host, detail=dict(e.detail),
            )
        return self.rc

    def finish_watch(self, spec, grace_s):
        self.calls.append("finish")
        if self.kill is None:
            return None, None
        return self.kill, "lab/runs/kills/%s-%d.json" % (spec.run_id, spec.trial)

    def events_for(self, spec):
        return read_trial_events(self.events_dir, spec.run_id, spec.trial)

    def chain_problems(self):
        problems = []
        for path in sorted(self.events_dir.glob("*.jsonl")):
            problems += verify_chain(str(path))
        return problems
