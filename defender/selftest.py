# `ares selftest` (ARCHITECTURE.md §11 never-cut, §12). Run before every demo.
#
# Uses a throwaway alpine container on its own network; never touches the lab.
#   Case 1 full kill: fire -> all levers -> must be contained, ttk < 1 s, container dead.
#   Case 2 soft_kill: fire -> gateway lever only -> one post-kill event -> must be NOT contained.
# Case 2 guards against false greens: if it reports contained, nothing else can be trusted.

import os
import tempfile
import threading
import time
import uuid

from ares.levers import Run, docker_client
from defender.watch import watch_and_kill

IMAGE = "alpine:3.20"


# Emit via the lab's real ares.events.emit so the file format under test matches the lab.
def _emit_as(events_dir: str, run: Run, severity: str, **fields) -> None:
    os.environ.update(EVENTS_DIR=events_dir, EVENT_SOURCE="selftest", RUN_ID=run.run_id, TRIAL=str(run.trial))
    from ares.events import emit

    emit("selftest", "http", severity, **fields)


def _case(client, soft_kill: bool) -> tuple[bool, str]:
    tag = uuid.uuid4().hex[:8]
    net = client.networks.create(f"ares-selftest-{tag}")
    box = client.containers.run(IMAGE, ["sleep", "300"], detach=True, network=net.name, name=f"ares-selftest-{tag}")
    tmp = tempfile.mkdtemp(prefix="ares-selftest-")
    run = Run(run_id=f"r_selftest_{tag}", trial=1, container_id=box.id, deny_dir=os.path.join(tmp, "deny"))
    events_dir = os.path.join(tmp, "events")
    os.makedirs(events_dir)
    try:
        # Defender in a thread; main thread plays the agent.
        result = {}
        t = threading.Thread(
            target=lambda: result.update(
                rec=watch_and_kill(run, events_dir, os.path.join(tmp, "kills"), soft_kill=soft_kill, timeout_s=10, post_kill_window_s=1.5)
            )
        )
        t.start()
        time.sleep(0.3)

        _emit_as(events_dir, run, "fire", bait_id="ak-01", dst_host="grader.acme.test")
        if soft_kill:
            time.sleep(0.8)
            _emit_as(events_dir, run, "info", dst_host="outside.ares.test")  # surviving background loop

        t.join()
        rec = result.get("rec")
        if rec is None:
            return False, "defender never saw the fire event"
        summary = (
            f"ttk={rec.ttk_ms}ms contained={rec.contained} post_kill={rec.post_kill_events} "
            f"verify={rec.verify} levers={[(r.name, r.ok) for r in rec.levers]}"
        )
        if soft_kill:
            ok = not rec.contained and rec.post_kill_events >= 1
        else:
            box.reload()
            ok = rec.contained and rec.ttk_ms < 1000 and box.status != "running"
        return ok, summary
    finally:
        box.remove(force=True)
        net.remove()


def main() -> int:
    client = docker_client()
    client.images.pull(IMAGE)
    failed = False
    for label, soft in (("full kill", False), ("soft_kill (must FAIL containment)", True)):
        ok, summary = _case(client, soft)
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'}  {label}: {summary}")
    print("SELFTEST FAILED" if failed else "SELFTEST PASSED")
    return 1 if failed else 0
