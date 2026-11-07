"""scripts/pick_model.py decides which model a drill runs on, so its logic is
tested against a stub provider that reproduces what the real API did:
`/v1/models` lists ids the account cannot actually invoke.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import pick_model  # noqa: E402

REAL_CLIENT = httpx.Client  # captured before any monkeypatching

CATALOG = [
    "nvidia/nemotron-3-embed-1b",            # not chat -> filtered
    "nvidia/nemotron-parse",                 # not chat -> filtered
    "nvidia/nemotron-4-340b-reward",         # not chat -> filtered
    "nvidia/llama-3.1-nemotron-safety-guard-8b-v3",  # not chat -> filtered
    "nvidia/nemotron-3-super-120b-a12b",     # listed but 404 for this account
    "nvidia/nemotron-3.5-lightning-30b-a3b", # works, tools, fast
    "nvidia/nemotron-3-ultra-550b-a55b",     # works, text only, slow
    "nvidia/llama-3.1-nemotron-70b-instruct",# 410 gone
]

GONE = "nvidia/llama-3.1-nemotron-70b-instruct"
NOT_FOR_ACCOUNT = "nvidia/nemotron-3-super-120b-a12b"
WORKS_WITH_TOOLS = "nvidia/nemotron-3.5-lightning-30b-a3b"
WORKS_TEXT_ONLY = "nvidia/nemotron-3-ultra-550b-a55b"


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": i} for i in CATALOG]})

    body = json.loads(request.content)
    model = body["model"]
    if model == NOT_FOR_ACCOUNT:
        return httpx.Response(404, json={
            "status": 404, "title": "Not Found",
            # Shape of the real refusal, with the ids replaced: an account
            # identifier does not belong in the repo.
            "detail": "Function '<function-uuid>': Not found for account '<account-id>'"})
    if model == GONE:
        return httpx.Response(410, json={
            "status": 410, "title": "Gone",
            "detail": "has reached its end of life on 2026-08-26"})

    wants_tools = "tools" in body
    message = {"role": "assistant", "content": "ok"}
    if wants_tools and model == WORKS_WITH_TOOLS:
        message = {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "list_dir", "arguments": '{"path": "/workspace"}'}}]}
    return httpx.Response(200, json={
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"total_tokens": 9}})


def _client_factory(route):
    def fake_client(*a, **kw):
        kw.pop("timeout", None)
        kw.pop("transport", None)
        return REAL_CLIENT(transport=httpx.MockTransport(route), **kw)
    return fake_client


@pytest.fixture(autouse=True)
def stub_provider(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-FAKE")
    monkeypatch.setattr(sys, "argv", ["pick_model.py", "nemotron"])
    monkeypatch.setattr(pick_model.httpx, "Client", _client_factory(handler))
    yield


def test_recommends_the_fastest_model_that_does_tool_calling(capsys):
    rc = pick_model.main()
    out = capsys.readouterr().out
    assert rc == 0, out

    # Non-chat ids are never probed.
    for skipped in ("embed", "parse", "reward", "safety"):
        assert skipped not in out

    # The real failures are surfaced with their reasons, not swallowed.
    assert "Not found for account" in out
    assert "end of life" in out
    assert "410" in out and "404" in out

    assert "export ARES_MODEL=%s" % WORKS_WITH_TOOLS in out
    assert "WARNING" not in out  # one candidate did tools


def test_warns_when_nothing_supports_native_tool_calling(capsys, monkeypatch):
    """No candidate emits tool_calls, so the harness would need its text
    fallback -- which has never run against a real model. Say so loudly."""
    def text_only(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": WORKS_WITH_TOOLS}, {"id": WORKS_TEXT_ONLY}]})
        return httpx.Response(200, json={
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "ok"}}],
            "usage": {"total_tokens": 9}})

    monkeypatch.setattr(pick_model.httpx, "Client", _client_factory(text_only))
    rc = pick_model.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "text only" in out
    assert "WARNING" in out
    assert "fall back to parsing a JSON action block" in out
    assert "export ARES_MODEL=" in out  # still names the fastest that answers


def test_reports_when_nothing_is_callable(capsys, monkeypatch):
    def all_dead(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": NOT_FOR_ACCOUNT}]})
        return httpx.Response(404, json={"detail": "Not found for account"})

    monkeypatch.setattr(pick_model.httpx, "Client", _client_factory(all_dead))
    assert pick_model.main() == 1
    out = capsys.readouterr().out
    assert "Nothing in this family is callable" in out
    assert "pick_model.py llama" in out
