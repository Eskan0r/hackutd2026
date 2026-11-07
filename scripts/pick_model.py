#!/usr/bin/env python3
"""Find a model this account can actually invoke, and say whether it does tools.

`GET /v1/models` lists NVIDIA's whole catalog, not what your key may call: a
listed id can still fail with 404 "Function '<uuid>': Not found for account",
and an id that worked last month can be 410 Gone. So probe instead of guess.

    export NVIDIA_API_KEY=nvapi-...
    ./.venv/bin/python scripts/pick_model.py

Spends about one call per candidate, plus one more per candidate that works (the
tool-calling probe). Talks to the provider directly -- this runs on the control
plane, where the real key already lives.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gateway.main import UPSTREAMS  # noqa: E402

PROVIDER = os.environ.get("ARES_PROVIDER", "nvidia")

# Not chat models: embeddings, parsers, rerankers, classifiers.
NOT_CHAT = ("embed", "parse", "reward", "safety", "rerank", "ocr")

TOOL_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "List the entries of a directory.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]},
    },
}]


def candidates(client: httpx.Client, base: str, want: str):
    r = client.get(base + "/models")
    r.raise_for_status()
    ids = sorted(m.get("id", "") for m in r.json().get("data", []))
    out = []
    for i in ids:
        low = i.lower()
        if want and want not in low:
            continue
        if any(bad in low for bad in NOT_CHAT):
            continue
        out.append(i)
    return out


def probe(client: httpx.Client, base: str, model: str):
    """Returns (ok, status, latency_ms, note)."""
    t0 = time.perf_counter()
    try:
        r = client.post(base + "/chat/completions", json={
            "model": model, "max_tokens": 8, "temperature": 0,
            "messages": [{"role": "user", "content": "Reply with the word ok."}],
        })
    except httpx.HTTPError as exc:
        return False, 0, 0, str(exc)[:60]
    ms = int((time.perf_counter() - t0) * 1000)
    if r.status_code == 200:
        return True, 200, ms, ""
    detail = ""
    try:
        body = r.json()
        detail = str(body.get("detail") or body.get("title") or "")[:72]
    except ValueError:
        detail = r.text[:72]
    return False, r.status_code, ms, detail


def probe_tools(client: httpx.Client, base: str, model: str):
    """D2 needs the agent to take bait through tools, so this is decisive."""
    try:
        r = client.post(base + "/chat/completions", json={
            "model": model, "max_tokens": 128, "temperature": 0,
            "tools": TOOL_SCHEMA,
            "messages": [{"role": "user",
                          "content": "List the files in /workspace. Use a tool."}],
        })
        if r.status_code != 200:
            return "no (%d)" % r.status_code
        msg = r.json()["choices"][0]["message"]
        return "yes" if msg.get("tool_calls") else "text only"
    except Exception:
        return "error"


def main() -> int:
    key_env = UPSTREAMS.get(PROVIDER, {}).get("key_env", "NVIDIA_API_KEY")
    base = UPSTREAMS.get(PROVIDER, {}).get("base_url", "")
    key = os.environ.get(key_env)
    if not key:
        print("%s is not set. Get a free key at https://build.nvidia.com" % key_env)
        return 2

    want = (sys.argv[1] if len(sys.argv) > 1 else "nemotron").lower()
    headers = {"Authorization": "Bearer %s" % key, "content-type": "application/json"}

    with httpx.Client(timeout=90, headers=headers) as client:
        try:
            models = candidates(client, base, want)
        except Exception as exc:
            print("could not list models: %s" % exc)
            return 1
        if not models:
            print("no chat candidates matching %r" % want)
            return 1

        print("\nprobing %d candidate(s) matching %r on %s\n" % (len(models), want, PROVIDER))
        print("  %-44s %-6s %8s  %s" % ("model", "call", "ms", "note"))
        print("  " + "-" * 78)

        working = []
        for model in models:
            ok, status, ms, note = probe(client, base, model)
            print("  %-44s %-6s %8s  %s" % (
                model, "OK" if ok else str(status), ms if ms else "-", note))
            if ok:
                working.append((model, ms))

        if not working:
            print("\nNothing in this family is callable with your key.")
            print("Try another family, e.g.:  ./.venv/bin/python scripts/pick_model.py llama")
            return 1

        print("\n  tool calling (what D2 depends on)")
        print("  " + "-" * 78)
        tool_ok = []
        for model, ms in working:
            verdict = probe_tools(client, base, model)
            print("  %-44s %s" % (model, verdict))
            if verdict == "yes":
                tool_ok.append((model, ms))

        best = (sorted(tool_ok, key=lambda x: x[1]) or sorted(working, key=lambda x: x[1]))[0]
        print("\nUse this:\n  export ARES_MODEL=%s" % best[0])
        if not tool_ok:
            print("\n  WARNING: none of these emitted a native tool call, so the harness"
                  "\n  will fall back to parsing a JSON action block out of plain text."
                  "\n  That fallback has not been exercised against a real model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
