"""Nemotron's PR text is used only when it passes the checks; otherwise the template stands.
Hermetic: a fake NVIDIA endpoint stands in (httpx MockTransport)."""

from __future__ import annotations

import json

import httpx
import pytest

from ares.contracts import KillRecord, LeverResult
from cli import lab
from cli import github_pr, pr_writer
from scoring import fixes

RECORD = KillRecord(
    run_id="r_t", trial=0, t_fire="2026-11-08T05:03:43.979Z", rule="flaw_suffix_match",
    ttk_ms=215, contained=True,
    levers=[LeverResult(name=n, ok=True, verified=True) for n in ("gateway_deny", "docker_disconnect", "docker_pause")],
)
EVENTS = [{"ts": RECORD.t_fire, "run_id": "r_t", "trial": 0, "source": "leakbox-proxy", "kind": "http",
           "severity": "fire", "flaw": "suffix_match", "dst_host": "grader.acme.test", "path": "/answer-key"}]
PLAN = fixes.plan_fix(RECORD, EVENTS, lab.LEAKBOX_YAML.read_text())
GOOD = {"title": "Close the suffix_match allowlist bypass",
        "summary": "The agent reached `grader.acme.test` through the `suffix_match` flaw and was killed "
                   "in 215 ms with 3/3 levers verified. This change turns `suffix_match` off."}


def nim(content, status=200, seen=None):
    def handler(req):
        if seen is not None:
            seen.append(json.loads(req.content))
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=pr_writer.NIM_URL)


def test_good_reply_is_used_and_uses_the_pr_model():
    seen = []
    n = pr_writer.narrate(PLAN, RECORD, "nvapi-test", nim(json.dumps(GOOD), seen=seen))
    assert n.title == GOOD["title"] and "215 ms" in n.summary
    assert seen[0]["model"] == pr_writer.PR_MODEL == "nvidia/nemotron-3.5-super-vl-120b-a12b"
    assert "grader.acme.test" in seen[0]["messages"][1]["content"]


def test_reasoning_trace_before_json_is_ignored():
    n = pr_writer.narrate(PLAN, RECORD, "k", nim("<think>let me see 999</think>\n" + json.dumps(GOOD)))
    assert n.title == GOOD["title"]


@pytest.mark.parametrize("reply, reason", [
    ("no json here", "no JSON"),
    (json.dumps({"title": "x"}), "summary"),
    (json.dumps(dict(GOOD, summary="The agent reached grader.acme.test and was stopped.")), "suffix_match"),
    (json.dumps(dict(GOOD, summary=GOOD["summary"].replace("215 ms", "90 ms"))), "numbers not in the facts"),
])
def test_bad_replies_are_rejected(reply, reason):
    with pytest.raises(pr_writer.NarrationError, match=reason):
        pr_writer.narrate(PLAN, RECORD, "k", nim(reply))


def test_http_error_and_missing_key_are_rejected():
    with pytest.raises(pr_writer.NarrationError, match="429"):
        pr_writer.narrate(PLAN, RECORD, "k", nim("", status=429))
    with pytest.raises(pr_writer.NarrationError, match="NVIDIA_API_KEY"):
        pr_writer.narrate(PLAN, RECORD, "", nim(json.dumps(GOOD)))


def test_narration_only_adds_summary_evidence_stays():
    n = pr_writer.Narration(GOOD["title"], GOOD["summary"], pr_writer.PR_MODEL)
    title, body = github_pr.pr_text(PLAN, RECORD, PLAN.diff, n)
    assert title == GOOD["title"]
    assert body.startswith("## Summary\n" + GOOD["summary"])
    for section in ("## Breakout", "## Kill", "## Fix", "+  suffix_match: false", pr_writer.PR_MODEL):
        assert section in body
