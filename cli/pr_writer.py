"""Nemotron writes the fix PR's title and summary. It narrates; it never decides.

The cause, the change and the evidence are fixed before this runs (scoring/fixes.py). The model is
given only those facts and asked for a title and a short summary. Its reply is used only if it
passes checks in code: valid JSON, names every fixed flaw and the host reached, and contains no
number that is not in the facts. Anything else raises NarrationError and the caller falls back to
the fixed template, so a bad reply can make the PR plainer but never wrong.

Uses NVIDIA_API_KEY, the same key the agent under test uses, against a different model.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ares.contracts import KillRecord
from scoring import fixes

NIM_URL = "https://integrate.api.nvidia.com/v1"
PR_MODEL = os.environ.get("ARES_PR_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")

SYSTEM = (
    "You write GitHub pull request titles and summaries for Ares, a tool that tests whether an AI "
    "agent's sandbox contains it. Use only the facts in the JSON you are given. Do not add hosts, "
    "numbers, files, causes or claims that are not in it. Write the flaw name and the host exactly "
    "as they appear in the JSON, in backticks. Reply with only a JSON object: "
    '{"title": "<under 80 characters>", "summary": "<2 to 4 plain sentences: what the agent '
    'reached, which flaw allowed it, how the kill went, and what this change fixes>"}'
)


class NarrationError(Exception):
    pass


@dataclass(frozen=True)
class Narration:
    title: str
    summary: str
    model: str


def facts(plan: fixes.FixPlan, record: KillRecord) -> Dict[str, Any]:
    c = plan.cause
    return {
        "run_id": record.run_id,
        "trial": record.trial,
        "reached": "%s%s" % (c.dst_host or "", c.path or ""),
        "bait_id": c.bait_id,
        "flaw": c.flaw,
        "fired_at": c.ts,
        "kill": {
            "contained": record.contained,
            "time_to_kill_ms": record.ttk_ms,
            "levers_verified": "%d/%d" % (sum(1 for r in record.levers if r.verified), len(record.levers)),
            "post_kill_leaks": record.post_kill_leaks,
        },
        "change": {"file": fixes.LEAKBOX_PATH,
                   "flaws_turned_off": plan.flaws,
                   "fixes": [{"title": fixes.FIXES[f].title, "why": fixes.FIXES[f].why} for f in plan.flaws]},
        "not_fixed": plan.unresolved,
    }


def _parse(content: str) -> Dict[str, Any]:
    text = re.sub(r"(?s)<think>.*?</think>", "", content or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise NarrationError("reply had no JSON object")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        raise NarrationError("reply JSON did not parse")
    if not isinstance(data, dict):
        raise NarrationError("reply JSON was not an object")
    return data


def check(data: Dict[str, Any], known: Dict[str, Any], must_name: List[str]) -> Narration:
    """Accept the reply only if it names `must_name` and adds no number that is not in `known`."""
    title, summary = data.get("title"), data.get("summary")
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 100:
        raise NarrationError("title missing or too long")
    if not isinstance(summary, str) or not 0 < len(summary.strip()) <= 1200:
        raise NarrationError("summary missing or too long")
    missing = [m for m in must_name if m not in summary]
    if missing:
        raise NarrationError("summary does not name %s" % ", ".join(missing))
    blob = json.dumps(known)
    invented = [n for n in re.findall(r"\d+(?:\.\d+)?", title + " " + summary) if n not in blob]
    if invented:
        raise NarrationError("reply has numbers not in the facts: %s" % ", ".join(sorted(set(invented))))
    return Narration(title.strip(), summary.strip(), PR_MODEL)


def narrate_facts(known: Dict[str, Any], must_name: List[str], api_key: str,
                  client: Optional[httpx.Client] = None) -> Narration:
    """Ask the PR model for a title and summary of `known`; return it only if it passes `check`."""
    if not api_key:
        raise NarrationError("NVIDIA_API_KEY is not set")
    nim = client or httpx.Client(base_url=NIM_URL, timeout=90)
    try:
        r = nim.post("/chat/completions", headers={"Authorization": "Bearer %s" % api_key}, json={
            "model": PR_MODEL,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(known, indent=2)}],
            "temperature": 0.2,
            "max_tokens": 2048,  # room for a reasoning trace before the JSON
        })
    except httpx.HTTPError as exc:
        raise NarrationError("could not reach NVIDIA: %s" % exc)
    if r.status_code != 200:
        raise NarrationError("NVIDIA returned %d: %s" % (r.status_code, r.text[:200]))
    try:
        content = r.json()["choices"][0]["message"].get("content")
    except (ValueError, KeyError, IndexError):
        raise NarrationError("unexpected response shape")
    return check(_parse(content), known, must_name)


def narrate(plan: fixes.FixPlan, record: KillRecord, api_key: str,
            client: Optional[httpx.Client] = None) -> Narration:
    """One kill record (`ares fix --open-pr`)."""
    must = list(plan.flaws) + ([plan.cause.dst_host] if plan.cause.dst_host else [])
    return narrate_facts(facts(plan, record), must, api_key, client)
