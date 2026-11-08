"""The fix PR opener talks to GitHub correctly. Hermetic: a fake GitHub API stands in (httpx
MockTransport), so no token and no network are needed."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from ares.contracts import KillRecord, LeverResult
from cli import drill as lab
from cli import github_pr
from scoring import fixes

LEAKBOX = lab.LEAKBOX_YAML.read_text()
REPO = "acme/halcyon"
RECORD = KillRecord(
    run_id="r_t", trial=0, t_fire="2026-11-08T05:03:43.979Z", rule="flaw_suffix_match",
    ttk_ms=215, contained=True,
    levers=[LeverResult(name=n, ok=True, verified=True) for n in ("gateway_deny", "docker_disconnect", "docker_pause")],
)
EVENTS = [{"ts": RECORD.t_fire, "run_id": "r_t", "trial": 0, "source": "leakbox-proxy", "kind": "http",
           "severity": "fire", "flaw": "suffix_match", "dst_host": "grader.acme.test", "path": "/answer-key"}]


class FakeGitHub:
    def __init__(self, base_text=LEAKBOX, open_prs=()):
        self.base_text = base_text
        self.open_prs = list(open_prs)
        self.calls = []
        self.put = None
        self.pr = None

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.replace("/repos/%s" % REPO, "")
        self.calls.append((req.method, path))
        body = json.loads(req.content) if req.content else None
        if req.method == "GET" and path == "/pulls":
            return httpx.Response(200, json=self.open_prs)
        if req.method == "GET" and path == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "basesha"}})
        if req.method == "GET" and path == "/contents/lab/leakbox.yaml":
            return httpx.Response(200, json={"sha": "blobsha",
                                             "content": base64.b64encode(self.base_text.encode()).decode()})
        if req.method == "POST" and path == "/git/refs":
            return httpx.Response(201, json={})
        if req.method == "PUT" and path == "/contents/lab/leakbox.yaml":
            self.put = body
            return httpx.Response(201, json={})
        if req.method == "POST" and path == "/pulls":
            self.pr = body
            return httpx.Response(201, json={"html_url": "https://github.com/%s/pull/7" % REPO})
        return httpx.Response(404, json={"message": "not found"})


def client(fake):
    return httpx.Client(transport=httpx.MockTransport(fake), base_url="https://api.github.com")


def plan():
    return fixes.plan_fix(RECORD, EVENTS, LEAKBOX)


def test_opens_pr_with_only_the_fix():
    fake = FakeGitHub()
    url = github_pr.open_fix_pr(plan(), RECORD, REPO, "main", "tok", client(fake))

    assert url.endswith("/pull/7")
    assert [c[0] + " " + c[1] for c in fake.calls] == [
        "GET /pulls", "GET /git/ref/heads/main", "GET /contents/lab/leakbox.yaml",
        "POST /git/refs", "PUT /contents/lab/leakbox.yaml", "POST /pulls"]
    committed = base64.b64decode(fake.put["content"]).decode()
    assert committed == fixes.turn_off(LEAKBOX, "suffix_match")
    assert fake.put["branch"] == fake.pr["head"] == "ares/fix-suffix_match-r_t-t0"
    assert fake.put["sha"] == "blobsha" and fake.pr["base"] == "main"


def test_body_carries_the_evidence():
    fake = FakeGitHub()
    github_pr.open_fix_pr(plan(), RECORD, REPO, "main", "tok", client(fake))
    body = fake.pr["body"]
    for fact in ("r_t", "grader.acme.test/answer-key", "suffix_match", "215 ms",
                 "post-kill leaks: 0", "+  suffix_match: false"):
        assert fact in body
    assert "Match allowlist hosts exactly" in fake.pr["title"]


def test_existing_open_pr_is_reused():
    fake = FakeGitHub(open_prs=[{"html_url": "https://github.com/acme/halcyon/pull/3"}])
    url = github_pr.open_fix_pr(plan(), RECORD, REPO, "main", "tok", client(fake))
    assert url.endswith("/pull/3") and fake.put is None and fake.pr is None


def test_already_fixed_on_base_opens_nothing():
    fake = FakeGitHub(base_text=fixes.turn_off(LEAKBOX, "suffix_match"))
    with pytest.raises(github_pr.PRError, match="already off"):
        github_pr.open_fix_pr(plan(), RECORD, REPO, "main", "tok", client(fake))
    assert fake.put is None


def test_github_error_is_reported():
    def deny(req):
        return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
    with pytest.raises(github_pr.PRError, match="403"):
        github_pr.open_fix_pr(plan(), RECORD, REPO, "main", "tok", client(deny))


def test_unfixable_plan_opens_nothing():
    p = fixes.plan_fix(KillRecord(run_id="r_t", trial=0, t_fire="x", rule="bait_ak-01"), [], LEAKBOX)
    with pytest.raises(github_pr.PRError, match="nothing to fix"):
        github_pr.open_fix_pr(p, RECORD, REPO, "main", "tok", client(FakeGitHub()))


@pytest.mark.parametrize("url", ["https://github.com/Eskan0r/hackutd2026.git",
                                 "git@github.com:Eskan0r/hackutd2026.git"])
def test_repo_from_remote(monkeypatch, url):
    class P:
        stdout = url + "\n"
    monkeypatch.setattr(github_pr.subprocess, "run", lambda *a, **k: P)
    assert github_pr.repo_from_remote(".") == "Eskan0r/hackutd2026"


def test_seed_policy_adds_file_once():
    state = {"exists": False, "put": None}

    def handler(req):
        path = req.url.path.replace("/repos/%s" % REPO, "")
        if path == "":
            return httpx.Response(200, json={"default_branch": "main", "permissions": {"push": True}})
        if req.method == "GET" and path == "/contents/lab/leakbox.yaml":
            return httpx.Response(200 if state["exists"] else 404, json={})
        if req.method == "PUT":
            state["put"] = json.loads(req.content)
            return httpx.Response(201, json={})
        return httpx.Response(500, json={})

    gh = github_pr.GitHub(REPO, "tok", client(handler))
    assert gh.seed_policy(LEAKBOX) == ("main", True)
    assert base64.b64decode(state["put"]["content"]).decode() == LEAKBOX and state["put"]["branch"] == "main"
    state["exists"], state["put"] = True, None
    assert gh.seed_policy(LEAKBOX) == ("main", False) and state["put"] is None
