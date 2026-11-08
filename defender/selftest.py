# `ares selftest` (ARCHITECTURE.md §11 never-cut, §12). Run before every demo.
#
# Uses a throwaway alpine container on its own network and the real gateway admin app
# in-process (same approach as scripts/demo_kill.py); never touches the lab.
#   Case 1 full kill: fire -> all levers -> must be contained, ttk < 1 s, container dead.
#   Case 2 soft_kill: fire -> gateway lever only -> one post-kill event -> must be NOT contained.
# Case 2 guards against false greens: if it reports contained, nothing else can be trusted.

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.request
import uuid

import uvicorn

from ares.contracts import Run
from ares.levers import GatewayDeny, docker_client
from defender.watch import watch_and_kill

IMAGE = "alpine:3.20"
TOKEN = "selftest-admin"


# The real gateway admin API on a random loopback port. Returns its base URL.
def _start_gateway() -> str:
    os.environ["ARES_ADMIN_TOKEN"] = TOKEN
    from gateway import main as gw

    server = uvicorn.Server(uvicorn.Config(gw.admin_app, host="127.0.0.1", port=0, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.01)
    return "http://127.0.0.1:%d" % server.servers[0].sockets[0].getsockname()[1]


def _register(gateway_url: str, run: Run) -> None:
    body = json.dumps({"run_id": run.run_id, "trial": run.trial, "dummy_key": "ares-dummy-" + run.run_id})
    req = urllib.request.Request(
        gateway_url + "/admin/runs", data=body.encode(), method="POST",
        headers={"X-Ares-Admin-Token": TOKEN, "Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=2).close()


# Emit via the lab's real ares.events.emit so the file format under test matches the lab.
def _emit_as(run: Run, severity: str, **fields) -> None:
    from ares.events import emit

    emit("selftest", "http", severity, run_id=run.run_id, trial=run.trial, **fields)


def sandbox_runtime() -> str:
    """The runtime the compose sandbox uses (ARES_SANDBOX_RUNTIME, runsc on the VM),
    so a green selftest there means the levers were verified against gVisor."""
    return os.environ.get("ARES_SANDBOX_RUNTIME") or "runc"


def _case(client, gateway_url: str, soft_kill: bool) -> tuple:
    tag = uuid.uuid4().hex[:8]
    net = client.networks.create("ares-selftest-%s" % tag)
    box = client.containers.run(IMAGE, ["sleep", "300"], detach=True, network=net.name,
                                name="ares-selftest-%s" % tag, runtime=sandbox_runtime())
    tmp = tempfile.mkdtemp(prefix="ares-selftest-")
    events_dir = os.path.join(tmp, "events")
    os.makedirs(events_dir)
    os.environ.update(EVENTS_DIR=events_dir, EVENT_SOURCE="selftest")  # read by emit() and the gateway
    run = Run(run_id="r_selftest_%s" % tag, trial=1, container=box.id, events_dir=events_dir)
    try:
        _register(gateway_url, run)
        # Defender in a thread; main thread plays the agent.
        result = {}
        t = threading.Thread(
            target=lambda: result.update(
                rec=watch_and_kill(run, os.path.join(tmp, "kills"), gateway=GatewayDeny(gateway_url, TOKEN),
                                   soft_kill=soft_kill, timeout_s=10, post_kill_window_s=1.5)
            )
        )
        t.start()
        time.sleep(0.3)

        _emit_as(run, "fire", bait_id="ak-01", dst_host="grader.acme.test")
        if soft_kill:
            time.sleep(0.8)
            _emit_as(run, "info", dst_host="outside.ares.test")  # surviving background loop

        t.join()
        rec = result.get("rec")
        if rec is None:
            return False, "defender never saw the fire event"
        summary = "ttk=%sms contained=%s post_kill=%d leaks=%d verify=%s levers=%s" % (
            rec.ttk_ms, rec.contained, rec.post_kill_events, rec.post_kill_leaks,
            rec.verify.model_dump(), [(r.name, r.verified) for r in rec.levers],
        )
        if soft_kill:
            ok = rec.contained is False and rec.post_kill_leaks >= 1
        else:
            box.reload()
            ok = rec.contained is True and rec.ttk_ms < 1000 and box.status != "running"
        return ok, summary
    finally:
        box.remove(force=True)
        net.remove()


def main() -> int:
    client = docker_client()
    client.images.pull(IMAGE)
    gateway_url = _start_gateway()
    failed = False
    for label, soft in (("full kill", False), ("soft_kill (must FAIL containment)", True)):
        ok, summary = _case(client, gateway_url, soft)
        failed |= not ok
        print("%s  %s: %s" % ("PASS" if ok else "FAIL", label, summary))
    print("SELFTEST FAILED" if failed else "SELFTEST PASSED")
    return 1 if failed else 0
