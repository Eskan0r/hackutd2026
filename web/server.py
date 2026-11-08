"""Ares dashboard -- a read-only viewer over the drill's evidence.

The CLI is the real interface; this calls the same code paths and renders them
(ARCHITECTURE.md section 6). There is no endpoint here that starts a drill,
pulls a lever, writes an event or talks to Docker, and there should never be
one: a viewer that can act is a second control plane, and the whole point of
the event stream is that it is append-only and produced outside the agent's
reach.

    ./.venv/bin/python -m web.server            # http://127.0.0.1:8090

Drills are started from the CLI, not from here. `web/operator.py` is the one
surface that can start one, and it is a separate app on a separate port behind
an explicit flag (`python -m web.server --operator`); this module never gains a
route that acts.

Serving:
  GET /                      the page
  GET /api/capabilities      what this server can do (operator: false)
  GET /api/runs              every run with events on disk
  GET /api/run/{key}         the full view model for one run
  GET /api/run/{key}/report  just the report, also the download
  GET /api/run/{key}/stream  SSE: appended events as they land (live drills)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from web import model

STATIC = Path(__file__).resolve().parent / "static"

class RevalidatedStatic(StaticFiles):
    """Static files the browser must revalidate on every load.

    With no Cache-Control the browser guesses a freshness window and reuses
    imported ES modules without asking, so an edited scene.js kept running
    stale. ``no-cache`` still caches; the ETag turns each check into a 304.
    """

    def file_response(self, *args: Any, **kwargs: Any) -> Any:
        resp = super().file_response(*args, **kwargs)
        resp.headers["cache-control"] = "no-cache"
        return resp


app = FastAPI(title="Ares dashboard", docs_url=None, redoc_url=None)
app.mount("/static", RevalidatedStatic(directory=str(STATIC)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/capabilities")
async def api_capabilities() -> Dict[str, Any]:
    """What this server can do, so the page knows what to offer.

    Always `operator: false` here. The operator app overrides this with true and
    adds what a drill needs (recordings, the default goal); the page reads it to
    decide whether its terminal can start a drill or can only hand you the
    command to run yourself.

    This module deliberately does not import `cli.lab` to fill those in. The
    viewer cannot start a drill, so it has no business holding the handle to the
    thing that does.
    """
    return {"operator": False, "recordings": [], "default_goal": None, "busy": None}


@app.get("/api/runs")
async def api_runs() -> Dict[str, Any]:
    return {"runs": model.discover_runs(), "dirs": [str(d) for d in model.event_dirs()]}


def _view(key: str) -> Dict[str, Any]:
    try:
        return model.build_view(key)
    except KeyError:
        raise HTTPException(status_code=404, detail="no events on disk for %r" % key)


@app.get("/api/run/{key}")
async def api_run(key: str) -> JSONResponse:
    return JSONResponse(_view(key))


@app.get("/api/run/{key}/report")
async def api_report(key: str, download: bool = False) -> JSONResponse:
    report = _view(key)["report"]
    headers = {}
    if download:
        headers["content-disposition"] = (
            'attachment; filename="ares-report-%s.json"' % report["run_id"]
        )
    return JSONResponse(report, headers=headers)


async def _tail(key: str) -> AsyncIterator[str]:
    """Re-read the run and push it when the event files change.

    Polling a mtime beats inotify here: the writers are containers on a bind
    mount, where inotify from the host is unreliable, and a drill's event rate
    is a handful per second at most.
    """
    # A distinct sentinel, not None: an unresolvable run also yields a stamp of
    # None, and with `last = None` the two matched, so the stream opened and
    # then sent nothing but keepalives forever -- no first payload, no error.
    unset = object()
    last = unset
    while True:
        try:
            directory, _ = model.resolve_run(key)
            stamp = max(
                [p.stat().st_mtime_ns for p in directory.glob("*.jsonl")] or [0]
            )
        except (KeyError, OSError):
            stamp = None
        if stamp != last:
            last = stamp
            try:
                payload = json.dumps(model.build_view(key))
            except KeyError:
                payload = json.dumps(
                    {"error": "no events on disk for %s" % key}
                )
            yield "data: %s\n\n" % payload
        else:
            yield ": keepalive\n\n"
        await asyncio.sleep(0.5)


@app.get("/api/run/{key}/stream")
async def api_stream(key: str) -> StreamingResponse:
    return StreamingResponse(
        _tail(key),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        prog="python -m web.server", description=__doc__.splitlines()[0]
    )
    parser.add_argument(
        "--operator", action="store_true",
        help="Also serve POST /api/drill, so the page can start a drill. Off by "
             "default: the viewer is read-only, and this makes it a control "
             "plane. Binds 127.0.0.1 only.",
    )
    parser.add_argument("--port", type=int, default=None, help="Override the port.")
    args = parser.parse_args(argv)

    host = os.environ.get("ARES_WEB_HOST", "127.0.0.1")
    if args.operator:
        # Never off-loopback. This app can start containers, and a drill is not
        # something a stranger on the conference wifi gets to launch.
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise SystemExit(
                "operator mode binds loopback only; ARES_WEB_HOST=%r is not" % host
            )
        from web.operator import build_app

        port = args.port or int(os.environ.get("ARES_OPERATOR_PORT", "8091"))
        served = build_app()
        # flush: stdout is block-buffered when this is not a tty (piped to a
        # log, run under a process manager), and a warning nobody sees is not a
        # warning. This one says the page can now start a drill.
        print("!! operator mode: POST /api/drill enabled -- this page can start a drill",
              flush=True)
        print("   read-only viewer:  python -m web.server   (port %s)"
              % os.environ.get("ARES_WEB_PORT", "8090"), flush=True)
        print("   operator:          http://%s:%d" % (host, port), flush=True)
    else:
        port = args.port or int(os.environ.get("ARES_WEB_PORT", "8090"))
        served = app

    uvicorn.run(served, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
