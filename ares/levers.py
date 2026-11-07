# Kill levers (ARCHITECTURE.md D3, D4, §9.3).
#
# pull() requests the effect; verify() returns True only if the effect is observed.
# A lever whose pull() succeeds but verify() fails is a failure (kill-switch false green).

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import docker

from ares.contracts import LeverResult


@dataclass
class Run:
    run_id: str
    trial: int
    container_id: str  # sandbox; resolved via compose labels, never a model-supplied name
    deny_dir: str  # gateway-deny flag dir, shared with the LLM gateway


class Lever(Protocol):
    name: str

    def pull(self, run: Run) -> None: ...
    def verify(self, run: Run) -> bool: ...


# 2 s timeout so a hung Docker call can't stall the kill path.
def docker_client() -> docker.DockerClient:
    return docker.from_env(timeout=2)


# Lever 1: gateway deny. Writes <deny_dir>/<run_id>; the gateway must 403 every call while it exists.
# TODO(gateway): verify() should confirm a refusal in the gateway log, not just the flag file.
# Until then this proves intent, not effect.
class GatewayDeny:
    name = "gateway_deny"

    def pull(self, run: Run) -> None:
        os.makedirs(run.deny_dir, exist_ok=True)
        with open(os.path.join(run.deny_dir, run.run_id), "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())

    def verify(self, run: Run) -> bool:
        return os.path.exists(os.path.join(run.deny_dir, run.run_id))


# Lever 2: detach the sandbox from every network it's on (doesn't hardcode sandboxnet/labnet).
class DockerDisconnect:
    name = "docker_disconnect"

    def pull(self, run: Run) -> None:
        client = docker_client()
        container = client.containers.get(run.container_id)
        for net_name in container.attrs["NetworkSettings"]["Networks"]:
            client.networks.get(net_name).disconnect(container, force=True)

    def verify(self, run: Run) -> bool:
        container = docker_client().containers.get(run.container_id)
        return not container.attrs["NetworkSettings"]["Networks"]


# Lever 3: pause (freezes all processes, preserves state for evidence). The defender kills after recording.
class DockerPause:
    name = "docker_pause"

    def pull(self, run: Run) -> None:
        docker_client().containers.get(run.container_id).pause()

    def verify(self, run: Run) -> bool:
        return docker_client().containers.get(run.container_id).attrs["State"]["Paused"]


ALL_LEVERS: list[Lever] = [GatewayDeny(), DockerDisconnect(), DockerPause()]


# Never raises: a failed lever is recorded as ok=False and the next lever still runs.
def pull_and_verify(lever: Lever, run: Run) -> LeverResult:
    try:
        lever.pull(run)
        ok = lever.verify(run)
        error = None if ok else "pulled but effect not observed"
    except Exception as exc:  # noqa: BLE001
        ok, error = False, f"{type(exc).__name__}: {exc}"
    return LeverResult(name=lever.name, t=datetime.now(timezone.utc), ok=ok, error=error)


# Ground truth for containment, straight from docker inspect.
def inspect_state(container_id: str) -> dict:
    attrs = docker_client().containers.get(container_id).attrs
    return {
        "network_endpoint": bool(attrs["NetworkSettings"]["Networks"]),
        "paused": attrs["State"]["Paused"],
    }


# Resolve the lab sandbox by the labels compose sets (project ares-lab, service sandbox).
def find_sandbox(project: str = "ares-lab", service: str = "sandbox") -> str:
    matches = docker_client().containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={project}",
                f"com.docker.compose.service={service}",
            ]
        },
    )
    if len(matches) != 1:
        raise RuntimeError(f"expected 1 sandbox container, found {len(matches)}")
    return matches[0].id
