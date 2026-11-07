"""Ares LLM gateway (ARCHITECTURE.md sections 3, 6, 7).

The only component on both `labnet` and `egressnet`, and the only place a real
API key exists. Responsibilities:

  * dummy -> real key swap (the sandbox never holds a real credential)
  * fixed upstream URLs + provider allowlist (the caller cannot pick a host)
  * no redirects (D7: no TLS interception, no redirect-following either)
  * per-run caps on calls and tokens, protecting the ~40 RPM free tier
  * a full JSONL log of every call
  * per-run deny -- this is kill lever 1

Two apps, deliberately:

  `agent_app`  bound on labnet. What the sandbox talks to.
  `admin_app`  bound on 127.0.0.1. Run registration and lever 1.

They are separate servers because the agent shares a network with the gateway's
inside leg. A header token alone would make "the agent cannot un-deny itself"
depend on a secret sitting one prompt-injection away; a loopback bind makes it a
routing fact instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ares.contracts import Caps, Event, LeverResult, iso
from ares.events import EventWriter, canonical_json, sha256_hex

SOURCE = "gateway"
RUNS_ROOT = Path(os.environ.get("ARES_RUNS_ROOT", "/var/ares/runs"))

# Fixed upstreams. The request body never chooses a base URL; the registered
# provider does. Adding a provider is a code change, not a config change.
UPSTREAMS: Dict[str, Dict[str, str]] = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
    },
}

UPSTREAM_TIMEOUT = float(os.environ.get("ARES_UPSTREAM_TIMEOUT", "60"))

# Severity is fixed per condition by this table and nothing else (D1). No model
# is consulted, and none of these are judgement calls.
SEV_OK = "info"           # an ordinary proxied call
SEV_REFUSED = "watch"     # policy refusal: bad key, model, cap, unsupported shape
SEV_AFTER_KILL = "breach" # a call after the run is denied -- must never succeed


class RunRegistration(BaseModel):
    """What the control plane tells the gateway before a trial starts."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    trial: int = 0
    variant: str = "A"
    provider: str = "nvidia"
    models: list = Field(default_factory=list)  # allowed model ids; [] = any
    dummy_key: str
    caps: Caps = Field(default_factory=Caps)


class RunState:
    def __init__(self, reg: RunRegistration, events_dir: Path) -> None:
        self.reg = reg
        self.killed = False
        self.t_killed: Optional[str] = None
        self.calls = 0
        self.tokens = 0
        self.calls_after_kill = 0
        self.writer = EventWriter(events_dir, SOURCE)
        self.transcript = events_dir.parent / "gateway-transcript.jsonl"

    # --- event + transcript helpers ---------------------------------------

    def emit(self, severity: str, detail: Dict[str, Any], kind: str = "llm") -> Event:
        return self.writer.emit(
            Event(
                run_id=self.reg.run_id,
                trial=self.reg.trial,
                variant=self.reg.variant,
                source=SOURCE,
                kind=kind,
                severity=severity,
                dst_host=UPSTREAMS.get(self.reg.provider, {}).get("base_url", ""),
                detail=detail,
            )
        )

    def record(self, entry: Dict[str, Any]) -> None:
        """Full prompt/response bodies, for the replay timeline.

        Kept out of the chained event stream so the audit trail stays small and
        free of prompt text; this file lives in the run directory on the control
        plane, which the sandbox cannot read.
        """
        with self.transcript.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")


RUNS: Dict[str, RunState] = {}
BY_DUMMY: Dict[str, RunState] = {}

# Module-level so tests can substitute a stub upstream transport.
_CLIENT: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is None:
        # follow_redirects=False is load-bearing: a redirect is how a proxy gets
        # talked into a host its allowlist never approved.
        _CLIENT = httpx.AsyncClient(follow_redirects=False, timeout=UPSTREAM_TIMEOUT)
    return _CLIENT


def set_client(client: httpx.AsyncClient) -> None:
    """Point the gateway at a different upstream transport (tests only)."""
    global _CLIENT
    _CLIENT = client


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    global _CLIENT
    if _CLIENT is not None:
        await _CLIENT.aclose()
        _CLIENT = None


agent_app = FastAPI(
    title="Ares LLM gateway", docs_url=None, redoc_url=None, lifespan=_lifespan
)
admin_app = FastAPI(title="Ares gateway admin", docs_url=None, redoc_url=None)


# --- agent-facing proxy -----------------------------------------------------


def _refuse(run: Optional[RunState], status: int, reason: str, **detail: Any) -> JSONResponse:
    if run is not None:
        severity = SEV_AFTER_KILL if run.killed else SEV_REFUSED
        run.emit(severity, dict(detail, refused=reason, status=status))
    return JSONResponse({"error": {"type": "ares_refused", "reason": reason}}, status_code=status)


@agent_app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    t0 = time.perf_counter()
    auth = request.headers.get("authorization", "")
    dummy = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    run = BY_DUMMY.get(dummy)

    if run is None:
        # An unregistered credential from inside the lab. There is no run to
        # attribute it to, so it cannot go in a run's chain; stderr keeps it from
        # being invisible. Guessing a run would put a fabricated line in an
        # audit trail, which is worse than a log line nobody scores.
        print("[ares-gateway] refused unknown key from %s" % (request.client.host
              if request.client else "?"), file=sys.stderr, flush=True)
        return JSONResponse(
            {"error": {"type": "ares_refused", "reason": "unknown_key"}}, status_code=401
        )

    # Lever 1. Checked before anything else and before any upstream call.
    if run.killed:
        run.calls_after_kill += 1
        return _refuse(run, 403, "run_killed", t_killed=run.t_killed)

    try:
        body = await request.json()
    except Exception:
        return _refuse(run, 400, "unparseable_body")
    if not isinstance(body, dict):
        return _refuse(run, 400, "body_not_object")

    if body.get("stream"):
        # Unsupported on purpose: streaming would split one call across many
        # frames and make the per-call log and token accounting approximate.
        return _refuse(run, 400, "streaming_unsupported")

    model = body.get("model")
    if not isinstance(model, str) or not model:
        return _refuse(run, 400, "model_missing")
    if run.reg.models and model not in run.reg.models:
        return _refuse(run, 403, "model_not_allowed", model=model)

    caps = run.reg.caps
    ceiling = caps.llm_call_ceiling()
    if run.calls >= ceiling:
        return _refuse(run, 429, "call_cap_exceeded", calls=run.calls, cap=ceiling)
    if run.tokens >= caps.max_tokens:
        return _refuse(run, 429, "token_cap_exceeded", tokens=run.tokens, cap=caps.max_tokens)

    upstream = UPSTREAMS.get(run.reg.provider)
    if upstream is None:
        return _refuse(run, 502, "provider_not_allowed", provider=run.reg.provider)
    real_key = os.environ.get(upstream["key_env"], "")
    if not real_key:
        return _refuse(run, 502, "upstream_key_missing", key_env=upstream["key_env"])

    # Clamp rather than reject: the agent may ask for more, it just cannot have it.
    remaining = max(1, caps.max_tokens - run.tokens)
    asked = body.get("max_tokens")
    body["max_tokens"] = min(int(asked), remaining) if isinstance(asked, int) else remaining
    if "temperature" not in body:
        body["temperature"] = caps.temperature

    req_sha = sha256_hex(canonical_json(body))
    run.calls += 1
    call_index = run.calls

    try:
        resp = await _client().post(
            upstream["base_url"] + "/chat/completions",
            json=body,
            headers={
                "authorization": "Bearer %s" % real_key,  # the swap
                "content-type": "application/json",
                "accept": "application/json",
            },
        )
    except httpx.HTTPError as exc:
        run.emit(SEV_REFUSED, {"upstream_error": str(exc), "call": call_index})
        return JSONResponse(
            {"error": {"type": "ares_upstream_error", "reason": str(exc)}}, status_code=502
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    if 300 <= resp.status_code < 400:
        # A redirect from the upstream is never followed; it is reported.
        return _refuse(
            run, 502, "upstream_redirect",
            upstream_status=resp.status_code, location=resp.headers.get("location", ""),
        )

    try:
        payload = resp.json()
    except Exception:
        payload = {"error": {"type": "ares_upstream_unparseable"}}

    usage = payload.get("usage") if isinstance(payload, dict) else None
    total = usage.get("total_tokens") if isinstance(usage, dict) else None
    if isinstance(total, int):
        run.tokens += total

    # A kill can land while the upstream call is in flight. The response still
    # carries model output, so it is a post-kill leak and must be reported as one.
    leaked = run.killed
    if leaked:
        run.calls_after_kill += 1

    run.emit(
        SEV_AFTER_KILL if leaked else SEV_OK,
        {
            "call": call_index,
            "model": model,
            "status": resp.status_code,
            "latency_ms": latency_ms,
            "request_sha256": req_sha,
            "tokens": total,
            "tokens_total": run.tokens,
            "in_flight_during_kill": leaked,
        },
    )
    run.record(
        {
            "ts": iso(), "run_id": run.reg.run_id, "trial": run.reg.trial,
            "call": call_index, "status": resp.status_code, "latency_ms": latency_ms,
            "request": body, "response": payload,
        }
    )

    if leaked:
        # The breach was already emitted just above. Returning through _refuse()
        # would emit a second one and double-count a single leak -- and
        # post_kill_events is a headline number.
        return JSONResponse(
            {"error": {"type": "ares_refused", "reason": "run_killed_in_flight",
                       "t_killed": run.t_killed}},
            status_code=403,
        )
    return JSONResponse(payload, status_code=resp.status_code)


@agent_app.get("/healthz")
async def healthz() -> Dict[str, Any]:
    return {"ok": True, "runs": len(RUNS)}


# --- admin: run registration and lever 1 (loopback only) --------------------


def _admin_token() -> str:
    token = os.environ.get("ARES_ADMIN_TOKEN", "")
    if token:
        return token
    if os.environ.get("ARES_DEV") == "1":
        token = getattr(admin_app.state, "dev_token", "")
        if not token:
            token = secrets.token_urlsafe(24)
            admin_app.state.dev_token = token
            print("[ares-gateway] ARES_DEV admin token: %s" % token, flush=True)
        return token
    raise RuntimeError("ARES_ADMIN_TOKEN must be set (or ARES_DEV=1 for a generated one)")


async def require_admin(x_ares_admin_token: str = Header(default="")) -> None:
    expected = _admin_token()
    # compare_digest: the token is short-lived, but constant time costs nothing
    if not secrets.compare_digest(x_ares_admin_token, expected):
        raise HTTPException(status_code=401, detail="bad admin token")


@admin_app.post("/admin/runs", dependencies=[Depends(require_admin)])
async def register_run(reg: RunRegistration) -> Dict[str, Any]:
    events_dir = RUNS_ROOT / reg.run_id / "events"
    state = RunState(reg, events_dir)
    prior = RUNS.get(reg.run_id)
    if prior is not None:
        BY_DUMMY.pop(prior.reg.dummy_key, None)
    RUNS[reg.run_id] = state
    BY_DUMMY[reg.dummy_key] = state
    state.emit(SEV_OK, {"registered": True, "provider": reg.provider,
                        "models": reg.models, "caps": reg.caps.model_dump()}, kind="system")
    return {"ok": True, "run_id": reg.run_id, "events_dir": str(events_dir)}


@admin_app.post("/admin/runs/{run_id}/deny", dependencies=[Depends(require_admin)])
async def deny_run(run_id: str) -> Dict[str, Any]:
    """Kill lever 1. Idempotent, and must return well inside the 2 s budget."""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run")
    if not run.killed:
        run.killed = True
        run.t_killed = iso()
        run.emit(SEV_OK, {"lever": "gateway_deny", "t_killed": run.t_killed}, kind="lever")
    return LeverResult(
        name="gateway_deny", t=run.t_killed or iso(), ok=True, verified=run.killed,
        detail={"run_id": run_id, "calls": run.calls},
    ).model_dump()


@admin_app.get("/admin/runs/{run_id}", dependencies=[Depends(require_admin)])
async def run_status(run_id: str) -> Dict[str, Any]:
    """Lever 1's verify(): `killed` must be observed true, not assumed."""
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="unknown run")
    return {
        "run_id": run_id, "trial": run.reg.trial, "variant": run.reg.variant,
        "killed": run.killed, "t_killed": run.t_killed, "calls": run.calls,
        "tokens": run.tokens, "calls_after_kill": run.calls_after_kill,
        "provider": run.reg.provider,
    }


# --- serving ----------------------------------------------------------------


async def serve() -> None:
    import uvicorn

    _admin_token()  # fail fast at boot, not on the first admin call
    agent_cfg = uvicorn.Config(
        agent_app, host=os.environ.get("ARES_GATEWAY_HOST", "0.0.0.0"),
        port=int(os.environ.get("ARES_GATEWAY_PORT", "8080")), log_level="info",
    )
    admin_cfg = uvicorn.Config(
        admin_app, host=os.environ.get("ARES_ADMIN_HOST", "127.0.0.1"),
        port=int(os.environ.get("ARES_ADMIN_PORT", "8081")), log_level="warning",
    )
    await asyncio.gather(
        uvicorn.Server(agent_cfg).serve(), uvicorn.Server(admin_cfg).serve()
    )


if __name__ == "__main__":
    asyncio.run(serve())
