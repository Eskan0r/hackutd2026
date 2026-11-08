"""Ares dashboard -- a read-only viewer over the drill's evidence.

The CLI is the real interface; this calls the same code paths and renders them
(ARCHITECTURE.md section 6). There is no endpoint here that starts a drill,
pulls a lever, writes an event or talks to Docker, and there should never be
one: a viewer that can act is a second control plane, and the whole point of
the event stream is that it is append-only and produced outside the agent's
reach.

    ./.venv/bin/python -m web.server            # http://127.0.0.1:8090

Serving:
  GET /                      the page
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
from typing import Any, AsyncIterator, Dict

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


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("ARES_WEB_HOST", "127.0.0.1"),
        port=int(os.environ.get("ARES_WEB_PORT", "8090")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
