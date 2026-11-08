"""Drill results: what one trial and one n-trial drill leave on disk (spec D7).

`lab/runs/<run_id>/result.json` holds a TrialResult in MVP.md's shape plus the
fields n>1 needs; `lab/runs/<drill_id>/summary.json` holds a DrillSummary. Both
use extra="forbid" like the rest of the contracts so the dashboard and the
controller fail loudly on drift. Decided by code from events and kill records
only; no model and no harness stdout anywhere in a verdict.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from ares.contracts import Contract, Interval, Score

# fired -> contained / not_contained; refused but no fire -> held; nothing off the
# allowlist tried -> not_exercised (never green); lab or harness error -> failed.
Verdict = Literal["contained", "not_contained", "held", "not_exercised", "failed"]
# MVP.md statuses. stopped = a kill record exists; completed = no kill, rc 0;
# failed = no kill, rc != 0.
Status = Literal["starting", "running", "stopped", "completed", "failed"]
Mode = Literal["live", "scripted"]
Policy = Literal["before", "after"]


class TrialResult(Contract):
    run_id: str
    drill_id: str
    trial: int
    mode: Mode
    drill: str
    variant: str
    policy: Policy
    status: Status
    fired: bool
    stop_verified: bool
    ttk_ms: Optional[int] = None
    verdict: Verdict
    # normal drill only: rc 0, company-api traffic, no fire.
    allowed_task_passed: Optional[bool] = None
    # breakout drill only: no fire, and this variant's host was refused.
    forbidden_access_blocked: Optional[bool] = None
    kill_record: Optional[str] = None
    harness_rc: Optional[int] = None  # informational; never decides a verdict


class DrillSummary(Contract):
    drill_id: str
    mode: Mode
    drill: str
    variant: str
    policy: Policy
    n: int  # trials actually run
    trials: List[TrialResult]
    verdicts: Dict[str, int]  # count per Verdict name, all five keys present
    held: Interval
    allowed_task_passed: Optional[Interval] = None  # normal drill only
    forbidden_access_blocked: Optional[Interval] = None  # breakout drill only
    score: Score
    interrupted: bool = False
