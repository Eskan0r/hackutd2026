"""scripts/live_check.py is the first thing run against a new key, so its own
control flow is tested here against a stub upstream. The real-key path (does
NVIDIA accept this key) is what the script itself checks; this covers everything
around it so a broken script never masquerades as a bad key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway import main as gw  # noqa: E402
from scripts import live_check  # noqa: E402

upstream = FastAPI()
SEEN: list = []


@upstream.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    SEEN.append({"auth": request.headers.get("authorization", ""), "body": body})
    tool_probe = "List the files" in json.dumps(body.get("messages", []))
    message = (
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "list_dir", "arguments": json.dumps({"path": "/workspace"})}}]}
        if tool_probe
        else {"role": "assistant", "content": "contained"}
    )
    return JSONResponse({
        "id": "cmpl-1",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
    })


@pytest.fixture(autouse=True)
def stub(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-FAKE-FOR-TEST")
    monkeypatch.setenv("ARES_RUNS_ROOT", str(tmp_path / "runs"))
    monkeypatch.setattr(gw, "RUNS_ROOT", tmp_path / "runs")
    gw.RUNS.clear()
    gw.BY_DUMMY.clear()
    SEEN.clear()
    gw.set_client(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), follow_redirects=False)
    )
    yield


def test_live_check_passes_all_stages(capsys):
    rc = live_check.main()
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "live Nemotron call" in out
    assert "native tool calling works" in out
    assert "lever 1 deny + verify" in out
    assert "call after kill refused (403 run_killed)" in out
    assert "Phase 1 path is good" in out
    # The dummy key never reached the upstream; the real one did.
    assert all(s["auth"] == "Bearer nvapi-FAKE-FOR-TEST" for s in SEEN)
    assert live_check.DUMMY_KEY not in json.dumps(SEEN)


def test_live_check_reports_missing_key(monkeypatch, capsys):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    rc = live_check.main()
    out = capsys.readouterr().out
    assert rc == 2
    assert "NVIDIA_API_KEY is not set" in out
    assert "Brev is for renting GPUs" in out
