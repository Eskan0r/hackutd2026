"""Drill loop: verdicts, result contracts, and the loop over a stub lab. No Docker.

Spec: docs/superpowers/specs/2026-11-07-variant-b-drill-loop-design.md
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ares.results import DrillSummary, TrialResult  # noqa: F401 (DrillSummary used later)


def _trial(**over):
    base = dict(
        run_id="d_x-00",
        drill_id="d_x",
        trial=0,
        mode="scripted",
        drill="breakout",
        variant="A",
        policy="before",
        status="stopped",
        fired=True,
        stop_verified=True,
        ttk_ms=412,
        verdict="contained",
    )
    base.update(over)
    return TrialResult(**base)


def test_trial_result_round_trips_and_forbids_extra_fields():
    t = _trial()
    assert TrialResult.model_validate_json(t.model_dump_json()) == t
    with pytest.raises(ValidationError):
        TrialResult(**{**t.model_dump(), "escaped": True})
    with pytest.raises(ValidationError):
        _trial(verdict="green")
