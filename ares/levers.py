# Kill levers (ARCHITECTURE.md D3, D4, §9.3).
#
# pull() requests the effect; verify() returns True only if the effect is observed.
# LeverResult.ok = pull went through; LeverResult.verified = effect observed. Only
# verified counts toward containment (ok without verified is the false green Ares exists to catch).

from __future__ import annotations

import json
import os
import urllib.request
from typing import Protocol

import docker

from ares.contracts import LeverResult, Run, iso


class Lever(Protocol):
    name: str

    def pull(self, run: Run) -> None: ...
    def verify(self, run: Run) -> bool: ...


# 2 s timeout so a hung Docker call can't stall the kill path.
def docker_client() -> docker.DockerClient:
    return docker.from_env(timeout=2)


# Lever 1: gateway deny via the gateway's admin API (gateway/main.py).
# POST /admin/runs/{run_id}/deny, then GET /admin/runs/{run_id} must show killed=true.
# The run must already be registered with the gateway; an unknown run 404s and the lever fails.
class GatewayDeny:
    name = "gateway_deny"

    def __init__(self, admin_url: str | None = None, token: str | None = None):
        self.admin_url = (
            admin_url or os.environ.get("ARES_ADMIN_URL", "http://127.0.0.1:8081")
        ).rstrip("/")
        # No default: the sandbox can route to the admin port, so this token is what
        # keeps the agent off lever 1. lab/docker-compose.yml requires it too.
        self.token = token or os.environ["ARES_ADMIN_TOKEN"]

    def _call(self, method: str, path: str) -> dict:
        req = urllib.request.Request(
            self.admin_url + path,
            method=method,
            headers={"X-Ares-Admin-Token": self.token},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:  # noqa: S310 - loopback admin port
            return json.loads(resp.read() or b"{}")

    def pull(self, run: Run) -> None:
        self._call("POST", "/admin/runs/%s/deny" % run.run_id)

    def verify(self, run: Run) -> bool:
        return self._call("GET", "/admin/runs/%s" % run.run_id).get("killed") is True


# Lever 2: detach the sandbox from every network it's on (doesn't hardcode sandboxnet/labnet).
class DockerDisconnect:
    name = "docker_disconnect"

    def pull(self, run: Run) -> None:
        client = docker_client()
        container = client.containers.get(run.container)
        for net_name in container.attrs["NetworkSettings"]["Networks"]:
            client.networks.get(net_name).disconnect(container, force=True)

    def verify(self, run: Run) -> bool:
        container = docker_client().containers.get(run.container)
        return not container.attrs["NetworkSettings"]["Networks"]


# Lever 3: pause (freezes all processes, preserves state for evidence). The defender kills after recording.
class DockerPause:
    name = "docker_pause"

    def pull(self, run: Run) -> None:
        docker_client().containers.get(run.container).pause()

    def verify(self, run: Run) -> bool:
        return docker_client().containers.get(run.container).attrs["State"]["Paused"]


def all_levers(gateway: GatewayDeny | None = None) -> list:
    return [gateway or GatewayDeny(), DockerDisconnect(), DockerPause()]


# Never raises: a failed lever is recorded and the next lever still runs.
def pull_and_verify(lever: Lever, run: Run) -> LeverResult:
    ok, verified, error = False, False, None
    try:
        lever.pull(run)
        ok = True
        verified = lever.verify(run)
        if not verified:
            error = "pulled but effect not observed"
    except Exception as exc:  # noqa: BLE001
        error = "%s: %s" % (type(exc).__name__, exc)
    return LeverResult(name=lever.name, t=iso(), ok=ok, verified=verified, error=error)


# Ground truth for containment, straight from docker inspect.
def inspect_state(container_id: str) -> dict:
    attrs = docker_client().containers.get(container_id).attrs
    return {
        "labnet_endpoint": bool(attrs["NetworkSettings"]["Networks"]),
        "paused": attrs["State"]["Paused"],
    }


# Resolve the lab sandbox by the labels compose sets (project ares-lab, service sandbox).
# What RUN_ID/TRIAL a lab container was started with. The fake services and the proxy
# stamp every event with their own environment (set at `compose up`), so a defender
# watching a different run id sees nothing and reports "not exercised" while the bait
# is being taken. That happened in the first pilot. Check before watching.
def env_identity(attrs: dict) -> tuple:
    env = dict(
        e.split("=", 1) for e in attrs.get("Config", {}).get("Env", []) if "=" in e
    )
    return env.get("RUN_ID"), int(env.get("TRIAL") or 0)


def lab_identity(service: str, project: str = "ares-lab") -> tuple:
    matches = docker_client().containers.list(
        filters={
            "label": [
                "com.docker.compose.project=%s" % project,
                "com.docker.compose.service=%s" % service,
            ]
        }
    )
    if not matches:
        raise RuntimeError("lab service %r is not running" % service)
    return env_identity(matches[0].attrs)


def find_sandbox(project: str = "ares-lab", service: str = "sandbox") -> str:
    matches = docker_client().containers.list(
        all=True,
        filters={
            "label": [
                "com.docker.compose.project=%s" % project,
                "com.docker.compose.service=%s" % service,
            ]
        },
    )
    if len(matches) != 1:
        raise RuntimeError("expected 1 sandbox container, found %d" % len(matches))
    return matches[0].id
