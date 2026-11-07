#!/usr/bin/env python3
"""Phase 1 live check (ARCHITECTURE.md section 11): one real Nemotron call
through the gateway, then proof that kill lever 1 refuses the next one.

Needs a real key. No Docker, no lab -- gateway and harness run in this process
against a loopback socket, so this isolates "is my key and gateway right?" from
"is the lab wired up?".

    export NVIDIA_API_KEY=nvapi-...
    ./.venv/bin/python scripts/live_check.py

Spends 2-3 LLM calls. Exits non-zero if any stage fails.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run from anywhere

from gateway import main as gw  # noqa: E402

MODEL = os.environ.get("ARES_MODEL", "nvidia/nemotron-3-super-120b-a12b")
PROVIDER = os.environ.get("ARES_PROVIDER", "nvidia")
RUN_ID = "r_livecheck"
DUMMY_KEY = "ares-dummy-livecheck"
ADMIN_TOKEN = "livecheck-admin"

OK, BAD = "  ok  ", " FAIL "


def _admin() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gw.admin_app), base_url="http://127.0.0.1",
        headers={"X-Ares-Admin-Token": ADMIN_TOKEN}, timeout=30,
    )


def _list_models(key_env: str, filter_text: str = ""):
    """Model ids this key can use. Runs on the control plane, where the real key
    already lives, so it talks to the provider directly rather than the gateway
    (which exposes only /v1/chat/completions)."""
    base = gw.UPSTREAMS.get(PROVIDER, {}).get("base_url", "")
    try:
        with httpx.Client(timeout=30) as c:
            r = c.get(base + "/models",
                      headers={"Authorization": "Bearer %s" % os.environ[key_env]})
        r.raise_for_status()
        ids = sorted(m.get("id", "") for m in r.json().get("data", []))
    except Exception as exc:
        return ["(could not list models: %s)" % exc]
    hits = [i for i in ids if filter_text in i] if filter_text else ids
    return hits[:20] or ids[:20] or ["(none returned)"]


def main() -> int:
    key_env = gw.UPSTREAMS.get(PROVIDER, {}).get("key_env", "NVIDIA_API_KEY")
    if not os.environ.get(key_env):
        print("%s %s is not set.\n"
              "       Get a free key at https://build.nvidia.com (no credit card,\n"
              "       no Brev credits -- Brev is for renting GPUs, not the hosted API)."
              % (BAD, key_env))
        return 2

    os.environ.setdefault("ARES_ADMIN_TOKEN", ADMIN_TOKEN)
    os.environ["ARES_ADMIN_TOKEN"] = ADMIN_TOKEN
    runs_root = os.environ.get("ARES_RUNS_ROOT", "./.ares-livecheck")
    gw.RUNS_ROOT = Path(runs_root)
    print("gateway   provider=%s model=%s" % (PROVIDER, MODEL))
    print("events    %s/%s/events/gateway.jsonl" % (runs_root, RUN_ID))

    config = uvicorn.Config(gw.agent_app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.02)
    if not server.started:
        print("%s gateway did not start" % BAD)
        return 1
    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = "http://127.0.0.1:%d/v1" % port

    failures = []
    try:
        async def register():
            async with _admin() as admin:
                r = await admin.post("/admin/runs", json={
                    "run_id": RUN_ID, "trial": 0, "variant": "A", "provider": PROVIDER,
                    "models": [MODEL], "dummy_key": DUMMY_KEY,
                    "caps": {"max_steps": 3, "max_tokens": 400, "max_wall_seconds": 60,
                             "temperature": 0.2, "max_llm_calls": 3},
                })
                r.raise_for_status()
        asyncio.run(register())
        print("%s run registered (dummy key %s...)" % (OK, DUMMY_KEY[:18]))

        # 1. A real call, with the dummy key. The real key is swapped in by the
        #    gateway and never exists on this side of the call.
        t0 = time.perf_counter()
        with httpx.Client(timeout=90) as c:
            r = c.post(base_url + "/chat/completions",
                       headers={"Authorization": "Bearer %s" % DUMMY_KEY},
                       json={"model": MODEL, "max_tokens": 32,
                             "messages": [{"role": "user",
                                           "content": "Reply with the single word: contained"}]})
        ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            failures.append("live call returned %d: %s" % (r.status_code, r.text[:300]))
            print("%s live Nemotron call (%d) %s" % (BAD, r.status_code, r.text[:200]))
            if r.status_code in (404, 410):
                # A model id goes end-of-life without warning, so turn a dead end
                # into the list of ids this key can actually use right now.
                print("       the model id is dead; asking the provider what is available...")
                for name in _list_models(key_env, "nemotron"):
                    print("         %s" % name)
                print("       re-run with: export ARES_MODEL=<one of the above>")
        else:
            payload = r.json()
            reply = payload["choices"][0]["message"].get("content", "")
            usage = payload.get("usage", {})
            print("%s live Nemotron call  %d ms  %s tokens" % (OK, ms, usage.get("total_tokens")))
            print("       reply: %r" % (reply or "")[:120].strip())

        # 2. Does this model drive the tool loop natively? Section D2 depends on
        #    the agent taking bait via tools, so knowing this now matters.
        from agent import harness
        driver = harness.ModelDriver(model=MODEL, base_url=base_url, api_key=DUMMY_KEY,
                                     temperature=0.2, max_tokens=256)
        try:
            action, text, used = driver.next_action([
                {"role": "system", "content": harness.DEFAULT_SYSTEM},
                {"role": "user", "content":
                 "List the files in /workspace. Use a tool; do not describe it."},
            ])
            if action:
                print("%s native tool calling works  -> %s(%s)"
                      % (OK, action["tool"], json.dumps(action.get("args") or {})[:80]))
            else:
                print("  warn  model returned text, not a tool call. The harness JSON-action\n"
                      "       fallback will be doing the work. text: %r" % (text or "")[:120])
        except Exception as exc:
            print("  warn  tool-call probe failed: %s: %s" % (type(exc).__name__, exc))

        # 3. Kill lever 1.
        async def deny():
            async with _admin() as admin:
                lever = (await admin.post("/admin/runs/%s/deny" % RUN_ID)).json()
                status = (await admin.get("/admin/runs/%s" % RUN_ID)).json()
                return lever, status
        lever, status = asyncio.run(deny())
        if not (lever["ok"] and status["killed"]):
            failures.append("lever 1 did not take: %s" % status)
            print("%s lever 1 deny" % BAD)
        else:
            print("%s lever 1 deny + verify (killed=%s)" % (OK, status["killed"]))

        with httpx.Client(timeout=30) as c:
            r = c.post(base_url + "/chat/completions",
                       headers={"Authorization": "Bearer %s" % DUMMY_KEY},
                       json={"model": MODEL, "max_tokens": 16,
                             "messages": [{"role": "user", "content": "are you there?"}]})
        if r.status_code == 403 and r.json()["error"]["reason"] == "run_killed":
            print("%s call after kill refused (403 run_killed)" % OK)
        else:
            failures.append("post-kill call returned %d, expected 403" % r.status_code)
            print("%s post-kill call returned %d" % (BAD, r.status_code))
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    if failures:
        print("\nFAILED:\n  - " + "\n  - ".join(failures))
        return 1
    print("\nPhase 1 path is good: harness -> gateway -> Nemotron, and lever 1 holds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
