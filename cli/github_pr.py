"""Open a GitHub pull request that applies a fix plan (scoring/fixes.py) to lab/leakbox.yaml.

Everything happens through the GitHub REST API, so the local checkout is never touched: read the
base branch, create a fix branch, commit the edited file to it, open the PR. The edit is re-applied
to the base branch's copy of the file, not the local one, so the PR diff is exactly what merging
would change.

Auth: GITHUB_TOKEN, a fine-grained token for this repo only with Contents and Pull requests
read/write.
"""

from __future__ import annotations

import base64
import re
import subprocess
from typing import List, Optional, Tuple

import httpx

from ares.contracts import KillRecord
from scoring import fixes

API = "https://api.github.com"


class PRError(Exception):
    pass


def repo_from_remote(cwd: str) -> str:
    """`owner/name` from the origin remote (https or ssh form)."""
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=cwd, text=True,
                         capture_output=True).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        raise PRError("origin is not a GitHub remote (%r); pass --repo owner/name" % url)
    return m.group(1)


def branch_name(plan: fixes.FixPlan, record: KillRecord) -> str:
    return "ares/fix-%s-%s-t%d" % ("-".join(plan.flaws), record.run_id, record.trial)


def pr_text(plan: fixes.FixPlan, record: KillRecord, diff: str) -> Tuple[str, str]:
    """Title and body from fixed templates. Every fact comes from the kill record or the events."""
    c = plan.cause
    title = "Fix: %s (run %s)" % ("; ".join(fixes.FIXES[f].title for f in plan.flaws), record.run_id)
    levers = ", ".join("%s %s" % (r.name, "✓" if r.verified else "✗") for r in record.levers)
    lines: List[str] = [
        "## Breakout",
        "Run `%s` trial %d reached `%s%s`%s at %s through the `%s` flaw." % (
            record.run_id, record.trial, c.dst_host or "?", c.path or "",
            " (bait `%s`)" % c.bait_id if c.bait_id else "", c.ts, c.flaw or "unknown"),
        "",
        "## Kill",
        "Contained: **%s** · time to kill: %s ms · levers: %s · post-kill leaks: %d" % (
            "yes" if record.contained else "NO", record.ttk_ms, levers or "none", record.post_kill_leaks),
        "",
        "## Fix",
    ]
    for f in plan.flaws:
        t = fixes.FIXES[f]
        lines.append("**%s.** %s" % (t.title, t.why))
        if t.rebuild:
            lines.append("_Takes effect only after the sandbox is rebuilt._")
        lines.append("")
    lines += ["```diff", diff.rstrip("\n"), "```", ""]
    if plan.unresolved:
        lines += ["## Not fixed here (needs manual review)"] + ["- %s" % r for r in plan.unresolved] + [""]
    lines.append("_Opened by `ares fix --open-pr`. The cause and the change come from fixed rules, not a "
                 "model. Not yet proven by a rerun on a held-out variant._")
    return title, "\n".join(lines)


def open_fix_pr(plan: fixes.FixPlan, record: KillRecord, repo: str, base: str, token: str,
                client: Optional[httpx.Client] = None) -> str:
    """Open (or find the already-open) fix PR. Returns its URL."""
    if not plan.fixable:
        raise PRError("nothing to fix: %s" % "; ".join(plan.unresolved))
    gh = client or httpx.Client(base_url=API, timeout=20)
    gh.headers.update({"Authorization": "Bearer %s" % token, "Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2022-11-28"})
    owner = repo.split("/")[0]
    branch = branch_name(plan, record)

    def call(method: str, path: str, **kw) -> httpx.Response:
        try:
            r = gh.request(method, "/repos/%s%s" % (repo, path), **kw)
        except httpx.HTTPError as exc:
            raise PRError("could not reach GitHub: %s" % exc)
        if r.status_code >= 400:
            raise PRError("GitHub %s %s -> %d: %s" % (method, path, r.status_code, r.text[:300]))
        return r

    existing = call("GET", "/pulls", params={"head": "%s:%s" % (owner, branch), "state": "open"}).json()
    if existing:
        return existing[0]["html_url"]

    base_sha = call("GET", "/git/ref/heads/%s" % base).json()["object"]["sha"]
    f = call("GET", "/contents/%s" % fixes.LEAKBOX_PATH, params={"ref": base}).json()
    old = base64.b64decode(f["content"]).decode("utf-8")
    new = old
    for flaw in plan.flaws:
        if not fixes.is_on(new, flaw):
            raise PRError("%s is already off on %s; nothing to change" % (flaw, base))
        new = fixes.turn_off(new, flaw)
    diff = fixes.unified_diff(old, new)
    title, body = pr_text(plan, record, diff)

    call("POST", "/git/refs", json={"ref": "refs/heads/%s" % branch, "sha": base_sha})
    call("PUT", "/contents/%s" % fixes.LEAKBOX_PATH, json={
        "message": title, "branch": branch, "sha": f["sha"],
        "content": base64.b64encode(new.encode("utf-8")).decode("ascii"),
    })
    pr = call("POST", "/pulls", json={"title": title, "head": branch, "base": base, "body": body}).json()
    return pr["html_url"]
