"""Operator mode: the one surface that can start a drill. Off by default.

`web/server.py` is a read-only viewer and stays that way -- every route on it
is GET, and `tests/test_web.py` pins that, because a viewer that can act is a
second control plane (ARCHITECTURE.md section 6). This module is the deliberate,
separately-launched exception:

    python -m web.server                # the viewer. GET only. no drill route.
    python -m web.server --operator     # this. POST /api/drill, port 8091.

Two apps, not one app with a flag, so the read-only guarantee is a property of
an object a test can hold rather than a branch somebody might take. The viewer
app is mounted underneath, so one port still serves the page and the evidence
API; the operator routes are registered first and therefore win.

What it does *not* do: judge anything. It calls `cli.drill.drill()` -- the same
function `ares drill` calls -- and reports the verdict `cli/verdict.py` reaches.
The dashboard cannot reach a conclusion the CLI would not.

Guard rails, because this thing can start containers:

  * 127.0.0.1 only, enforced at bind time in `web/server.py`.
  * One drill at a time. The lab is a single set of containers on fixed
    networks; two concurrent drills would fight over them and the events would
    interleave into one run's file.
  * No shell. Options are typed fields validated here, never a command string
    handed to a shell -- the terminal in the browser *looks* like a prompt, and
    a prompt that forwards arbitrary text to a shell is a remote code execution
    hole, demo or not.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ares.contracts import Caps
from cli import drill as lab
from cli.verdict import classify
from web import model
from web.server import app as viewer_app

# How long a finished job stays readable, so a reconnecting page can still pick
# up the ending it missed.
JOB_TTL_S = 30 * 60


class DrillRequest(BaseModel):
    """The options `ares drill` takes, as fields rather than a command line."""

    recording: Optional[str] = Field(
        default=None, description="Replay a recording from agent/recorded/. None runs live."
    )
    goal: str = Field(default=lab.DEFAULT_GOAL, max_length=2000)
    model: Optional[str] = Field(default=None, max_length=200)
    max_steps: int = Field(default=12, ge=1, le=60)
    max_tokens: int = Field(default=16000, ge=500, le=400000)
    max_wall_seconds: int = Field(default=90, ge=5, le=1800)
    kill: bool = True


@dataclass
class Job:
    """One drill, running or finished."""

    id: str
    command: str                                     # the equivalent CLI line
    state: str = "running"                           # running | done | error
    run_id: Optional[str] = None
    run_key: Optional[str] = None
    exit_code: Optional[int] = None
    verdict: Optional[str] = None
    lines: List[Dict[str, Any]] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    ended: Optional[float] = None

    def emit(self, tag: str, text: str) -> None:
        self.lines.append({"tag": tag, "text": text})

    def public(self) -> Dict[str, Any]:
        return {
            "job": self.id,
            "command": self.command,
            "state": self.state,
            "run_id": self.run_id,
            "run_key": self.run_key,
            "exit_code": self.exit_code,
            "verdict": self.verdict,
            "lines": list(self.lines),
        }


_jobs: Dict[str, Job] = {}
_lock = threading.Lock()


def _command_line(req: DrillRequest) -> str:
    """The `ares drill` invocation equivalent to this request.

    Echoed into the terminal so what the page did is reproducible in a shell --
    the CLI stays the real interface even when the click happened here.
    """
    parts = ["ares", "drill"]
    if req.recording:
        parts.append(req.recording)
    if req.model:
        parts += ["--model", req.model]
    if req.goal != lab.DEFAULT_GOAL:
        parts += ["--goal", json.dumps(req.goal)]
    if req.max_steps != 12:
        parts += ["--max-steps", str(req.max_steps)]
    if req.max_tokens != 16000:
        parts += ["--max-tokens", str(req.max_tokens)]
    if req.max_wall_seconds != 90:
        parts += ["--max-wall-seconds", str(req.max_wall_seconds)]
    parts.append("--kill" if req.kill else "--no-kill")
    return " ".join(parts)


def _run_key(run_id: str) -> Optional[str]:
    """`<dir slug>:<run_id>` for the events directory the lab writes to."""
    try:
        return model.run_key(lab.EVENTS_DIR, run_id)
    except Exception:  # noqa: BLE001 - a label, never worth failing a drill over
        return None


def _active() -> Optional[Job]:
    return next((j for j in _jobs.values() if j.state == "running"), None)


def _reap() -> None:
    cutoff = time.time() - JOB_TTL_S
    for job_id, job in list(_jobs.items()):
        if job.state != "running" and (job.ended or job.started) < cutoff:
            del _jobs[job_id]


def _work(job: Job, req: DrillRequest) -> None:
    """Run the trial. Exceptions become job state, never a dropped stream."""
    try:
        caps = Caps(
            max_steps=req.max_steps,
            max_tokens=req.max_tokens,
            max_wall_seconds=req.max_wall_seconds,
        )
        if req.recording is None and not (
            os.environ.get("NVIDIA_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
        ):
            job.emit("warn", "no NVIDIA_API_KEY set; the gateway will refuse model "
                             "calls (upstream_key_missing). Name a recording to run "
                             "without a key.")

        def on_run_id(run_id: str) -> None:
            job.run_id = run_id
            job.run_key = _run_key(run_id)
            job.emit("sys", "run %s" % run_id)

        trial = lab.drill(
            "scripted" if req.recording else "model",
            req.goal,
            req.recording,
            req.model,
            caps,
            on_step=lambda msg: job.emit("step", msg),
            kill=req.kill,
            on_run_id=on_run_id,
        )
    except lab.DrillError as exc:
        job.emit("error", str(exc))
        job.state, job.exit_code, job.verdict = "error", 2, "error"
        job.ended = time.time()
        return
    except Exception as exc:  # noqa: BLE001 - surface it in the terminal
        job.emit("error", "%s: %s" % (type(exc).__name__, exc))
        job.state, job.exit_code, job.verdict = "error", 2, "error"
        job.ended = time.time()
        return

    outcome = classify(trial, req.max_steps)
    o = trial.outcome
    job.emit("sys", "steps %s · tool calls %s · stopped: %s" % (
        o.get("steps") if o.get("steps") is not None else "-",
        len(o.get("tool_calls", [])), o.get("stop_reason")))
    record = outcome.kill_record
    if record is not None:
        job.emit("KILL", "t_fire %s" % record.get("t_fire"))
        job.emit("KILL", "t_verified %s" % record.get("t_verified"))
        job.emit("KILL", "ttk_ms %s   (fire -> verified)" % record.get("ttk_ms"))
        for lever in record.get("levers") or []:
            job.emit("KILL", "lever %-18s %s" % (
                lever.get("name"),
                "verified" if lever.get("verified") else
                "PULLED, NOT VERIFIED" if lever.get("ok") else "failed"))
        job.emit("KILL", "docker inspect: labnet_endpoint=%s paused=%s" % (
            (record.get("verify") or {}).get("labnet_endpoint"),
            (record.get("verify") or {}).get("paused")))
        job.emit("KILL", "post_kill_events=%s  post_kill_leaks=%s" % (
            record.get("post_kill_events"), record.get("post_kill_leaks")))
    for text in outcome.lines:
        job.emit("verdict-%s" % outcome.code, text)
    job.emit("sys", "exit %d" % outcome.exit_code)
    job.state = "done"
    job.exit_code = outcome.exit_code
    job.verdict = outcome.code
    job.ended = time.time()


def build_app() -> FastAPI:
    """The operator app: drill routes first, then the read-only viewer."""
    app = FastAPI(title="Ares operator", docs_url=None, redoc_url=None)

    @app.get("/api/capabilities")
    async def capabilities() -> Dict[str, Any]:
        job = _active()
        return {
            "operator": True,
            "recordings": lab.recordings(),
            "default_goal": lab.DEFAULT_GOAL,
            "busy": job.id if job else None,
        }

    @app.post("/api/drill")
    async def start(req: DrillRequest) -> JSONResponse:
        if req.recording is not None and req.recording not in lab.recordings():
            raise HTTPException(
                status_code=400,
                detail="unknown recording %r; one of: %s"
                       % (req.recording, ", ".join(lab.recordings())),
            )
        with _lock:
            _reap()
            busy = _active()
            if busy:
                # Not a queue: the second drill would share the first's
                # containers and its events would land in the same files.
                raise HTTPException(
                    status_code=409,
                    detail="a drill is already running (job %s); wait for it to finish"
                           % busy.id,
                )
            job = Job(id=uuid.uuid4().hex[:8], command=_command_line(req))
            job.emit("cmd", job.command)
            _jobs[job.id] = job
        threading.Thread(target=_work, args=(job, req), daemon=True,
                         name="ares-drill-%s" % job.id).start()
        return JSONResponse(job.public(), status_code=202)

    @app.get("/api/drill")
    async def current() -> Dict[str, Any]:
        _reap()
        job = _active()
        return {"running": job.public() if job else None,
                "jobs": [j.public() for j in _jobs.values()]}

    @app.get("/api/drill/{job_id}")
    async def one(job_id: str) -> Dict[str, Any]:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="no such job %r" % job_id)
        return job.public()

    @app.get("/api/drill/{job_id}/stream")
    async def stream(job_id: str) -> StreamingResponse:
        if job_id not in _jobs:
            raise HTTPException(status_code=404, detail="no such job %r" % job_id)

        async def events() -> AsyncIterator[str]:
            sent = 0
            while True:
                job = _jobs.get(job_id)
                if job is None:          # reaped under a long-lived stream
                    yield "event: gone\ndata: {}\n\n"
                    return
                if len(job.lines) > sent or job.state != "running":
                    payload = {
                        "state": job.state,
                        "run_id": job.run_id,
                        "run_key": job.run_key,
                        "exit_code": job.exit_code,
                        "verdict": job.verdict,
                        "lines": job.lines[sent:],
                    }
                    sent = len(job.lines)
                    yield "data: %s\n\n" % json.dumps(payload)
                    if job.state != "running":
                        return
                else:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    # Last: everything the read-only viewer serves (the page, /static, the
    # evidence API). Registered after the routes above, so it never shadows one.
    app.mount("/", viewer_app)
    return app
