"""Gateway invariants (ARCHITECTURE.md sections 3, 6).

Runs fully in-process: a stub upstream stands in for NVIDIA NIM, so no network
and no real key. What these assert is the boundary behaviour, not the plumbing:
the dummy key never leaves the gateway, lever 1 denies, and anything that slips
through after a kill is logged as a breach.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ares.events import verify_chain
from gateway import main as gw

ADMIN_TOKEN = "test-admin-token"
REAL_KEY = "nvapi-REAL-KEY-NEVER-LEAVES-GATEWAY"
DUMMY_KEY = "ares-dummy-r_test"

# --- stub upstream ----------------------------------------------------------

upstream = FastAPI()
SEEN: list = []


@upstream.post("/v1/chat/completions")
async def completions(request: Request):
    body = await request.json()
    SEEN.append({"auth": request.headers.get("authorization", ""), "body": body})
    if body.get("model") == "redirect-me":
        return JSONResponse({}, status_code=302, headers={"location": "http://elsewhere.test/v1"})
    return JSONResponse(
        {
            "id": "cmpl-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )


@pytest.fixture(autouse=True)
def wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("ARES_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("NVIDIA_API_KEY", REAL_KEY)
    monkeypatch.setattr(gw, "RUNS_ROOT", tmp_path / "runs")
    gw.RUNS.clear()
    gw.BY_DUMMY.clear()
    SEEN.clear()
    gw.set_client(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream), follow_redirects=False)
    )
    yield tmp_path


def _agent_client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gw.agent_app), base_url="http://gateway"
    )


def _admin_client():
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gw.admin_app), base_url="http://127.0.0.1",
        headers={"X-Ares-Admin-Token": ADMIN_TOKEN},
    )


async def _register(admin, **over):
    payload = {
        "run_id": "r_test", "trial": 7, "variant": "A", "provider": "nvidia",
        "models": ["nemotron-test"], "dummy_key": DUMMY_KEY,
        "caps": {"max_steps": 3, "max_tokens": 1000, "max_wall_seconds": 90,
                 "temperature": 0.2, "max_llm_calls": 3},
    }
    payload.update(over)
    r = await admin.post("/admin/runs", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _chat(model="nemotron-test", key=DUMMY_KEY, **extra):
    body = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    body.update(extra)
    return {"json": body, "headers": {"Authorization": "Bearer %s" % key}}


def _events(tmp_path):
    p = tmp_path / "runs" / "r_test" / "events" / "gateway.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()], p


def test_key_swap_and_happy_path(wiring):
    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin)
            r = await agent.post("/v1/chat/completions", **_chat())
            assert r.status_code == 200, r.text
            assert r.json()["choices"][0]["message"]["content"] == "ok"
    asyncio.run(body())

    # The swap: upstream saw the real key; the dummy never left the gateway.
    assert SEEN[0]["auth"] == "Bearer %s" % REAL_KEY
    assert DUMMY_KEY not in json.dumps(SEEN)

    events, path = _events(wiring)
    llm = [e for e in events if e["kind"] == "llm"]
    assert [e["severity"] for e in llm] == ["info"]
    assert llm[0]["detail"]["tokens"] == 15
    assert llm[0]["trial"] == 7
    assert verify_chain(path) == []


def test_unknown_dummy_key_refused(wiring):
    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin)
            r = await agent.post("/v1/chat/completions", **_chat(key="guessed-key"))
            assert r.status_code == 401
    asyncio.run(body())
    assert SEEN == []  # never reached the upstream


def test_lever_one_deny_then_breach(wiring):
    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin)
            assert (await agent.post("/v1/chat/completions", **_chat())).status_code == 200

            lever = (await admin.post("/admin/runs/r_test/deny")).json()
            assert lever["name"] == "gateway_deny"
            assert lever["ok"] is True and lever["verified"] is True

            # verify(): killed is observed, not assumed.
            status = (await admin.get("/admin/runs/r_test")).json()
            assert status["killed"] is True and status["t_killed"]

            r = await agent.post("/v1/chat/completions", **_chat())
            assert r.status_code == 403
            assert r.json()["error"]["reason"] == "run_killed"

            # Idempotent: the defender may pull twice.
            assert (await admin.post("/admin/runs/r_test/deny")).json()["ok"] is True
            assert (await admin.get("/admin/runs/r_test")).json()["calls_after_kill"] == 1
    asyncio.run(body())

    assert len(SEEN) == 1  # the post-kill call never reached the upstream
    events, path = _events(wiring)
    assert [e["severity"] for e in events if e["kind"] == "llm"] == ["info", "breach"]
    assert any(e["kind"] == "lever" for e in events)
    assert verify_chain(path) == []


def test_call_cap_and_model_allowlist(wiring):
    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin)
            for _ in range(3):
                assert (await agent.post("/v1/chat/completions", **_chat())).status_code == 200
            r = await agent.post("/v1/chat/completions", **_chat())
            assert r.status_code == 429
            assert r.json()["error"]["reason"] == "call_cap_exceeded"

            r = await agent.post("/v1/chat/completions", **_chat(model="gpt-4o"))
            assert r.json()["error"]["reason"] == "model_not_allowed"
    asyncio.run(body())
    assert len(SEEN) == 3
    events, _ = _events(wiring)
    assert [e["detail"].get("refused") for e in events if e["severity"] == "watch"] == [
        "call_cap_exceeded", "model_not_allowed"
    ]


def test_streaming_and_upstream_redirect_refused(wiring):
    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin, models=[])  # [] = any model
            r = await agent.post("/v1/chat/completions", **_chat(stream=True))
            assert r.json()["error"]["reason"] == "streaming_unsupported"

            r = await agent.post("/v1/chat/completions", **_chat(model="redirect-me"))
            assert r.status_code == 502
            assert r.json()["error"]["reason"] == "upstream_redirect"
    asyncio.run(body())


def test_max_tokens_clamped_to_remaining_budget(wiring):
    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin)
            await agent.post("/v1/chat/completions", **_chat(max_tokens=999_999))
    asyncio.run(body())
    assert SEEN[0]["body"]["max_tokens"] == 1000  # clamped to caps.max_tokens


def test_admin_requires_token(wiring):
    async def body():
        async with _agent_client() as agent:
            transport = httpx.ASGITransport(app=gw.admin_app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as bare:
                assert (await bare.post("/admin/runs/r_test/deny")).status_code == 401
            # The proxy port exposes no admin surface at all.
            assert (await agent.post("/admin/runs/r_test/deny")).status_code == 404
    asyncio.run(body())


def test_response_arriving_after_a_kill_is_a_breach(wiring):
    """A kill can land while an upstream call is in flight. The response still
    carries model output, so it must be logged as a leak and withheld from the
    agent -- not quietly returned because the request predated the kill.
    """
    killer = FastAPI()

    @killer.post("/v1/chat/completions")
    async def mid_flight(request: Request):
        gw.RUNS["r_test"].killed = True  # the defender pulls lever 1 right now
        gw.RUNS["r_test"].t_killed = "2026-11-07T19:02:11.412Z"
        return JSONResponse({
            "id": "cmpl-late",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "secret"},
                         "finish_reason": "stop"}],
            "usage": {"total_tokens": 21},
        })

    gw.set_client(
        httpx.AsyncClient(transport=httpx.ASGITransport(app=killer), follow_redirects=False)
    )

    async def body():
        async with _admin_client() as admin, _agent_client() as agent:
            await _register(admin)
            r = await agent.post("/v1/chat/completions", **_chat())
            assert r.status_code == 403
            assert r.json()["error"]["reason"] == "run_killed_in_flight"
            assert "secret" not in r.text  # output withheld from the agent
            assert (await admin.get("/admin/runs/r_test")).json()["calls_after_kill"] == 1
    asyncio.run(body())

    events, path = _events(wiring)
    llm = [e for e in events if e["kind"] == "llm"]
    assert [e["severity"] for e in llm] == ["breach"]
    assert llm[0]["detail"]["in_flight_during_kill"] is True
    assert verify_chain(path) == []
