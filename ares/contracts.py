"""Ares data contracts. Frozen early (ARCHITECTURE.md section 9).

Every producer and consumer of events, kill records and scores imports from here.
Models use extra="forbid" so contract drift fails loudly instead of silently
dropping fields on the floor.

Kept Python 3.9 compatible: the VM runs 3.12 in containers, but local dev here
is 3.9, so no PEP 604 unions outside `from __future__ import annotations`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ARES_VERSION = 1

# --- enumerations -----------------------------------------------------------

# Severity is FIXED PER EVENT SOURCE and decided by deterministic code. No model
# ever assigns one (design decision D1).
#   info   ordinary use
#   watch  lookalike DNS query, allowlisted package fetch
#   fire   bait touched, unknown domain, metadata token, flaw path used
#   breach host firewall hit, gateway call after kill, ANY event after t_verified
Severity = Literal["info", "watch", "fire", "breach"]

# tool_call: emitted by the gateway (never the in-sandbox harness) for each tool
# call in a model response; always severity "info" unless after t_verified.
EventKind = Literal["http", "dns", "llm", "tool_call", "file", "proc", "lever", "kill", "system"]

Provider = Literal["nvidia", "openrouter", "openai", "anthropic"]

LeverName = Literal["gateway_deny", "docker_disconnect", "docker_pause"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: Optional[datetime] = None) -> str:
    """Millisecond-precision RFC3339 with a trailing Z, as in section 9.2."""
    ts = ts or utcnow()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03dZ" % (ts.microsecond // 1000)
    )


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- 9.1 agent manifest (input, read-only) ----------------------------------


class ToolSpec(Contract):
    name: str
    scope: str


class Caps(Contract):
    max_steps: int = 12
    max_tokens: int = 6000
    max_wall_seconds: int = 90
    temperature: float = 0.2
    # Not in section 9.1, but the gateway needs a hard per-run LLM call ceiling
    # to protect the 40 RPM free tier. Derived from max_steps when unset.
    max_llm_calls: Optional[int] = None

    def llm_call_ceiling(self) -> int:
        if self.max_llm_calls is not None:
            return self.max_llm_calls
        return self.max_steps + 2  # steps plus a little slack for retries


class AgentSpec(Contract):
    name: str
    provider: Provider = "nvidia"
    model: str
    system_prompt_file: Optional[str] = None
    tools: List[ToolSpec] = Field(default_factory=list)
    caps: Caps = Field(default_factory=Caps)


class CredentialSpec(Contract):
    """Names only. Ares mints the synthetic values; real secrets never appear."""

    name: str
    kind: str


class EgressSpec(Contract):
    host: str
    port: int = 80
    proto: Literal["http", "https", "dns"] = "http"
    purpose: str = ""


class NetworkSpec(Contract):
    declared_egress: List[EgressSpec] = Field(default_factory=list)
    package_index: Optional[str] = None
    metadata_endpoint: bool = False


class MountSpec(Contract):
    path: str
    mode: Literal["ro", "rw"] = "ro"


class FilesystemSpec(Contract):
    workspace: str = "/workspace"
    mounts: List[MountSpec] = Field(default_factory=list)


class Manifest(Contract):
    ares_version: int = ARES_VERSION
    agent: AgentSpec
    credentials: List[CredentialSpec] = Field(default_factory=list)
    network: NetworkSpec = Field(default_factory=NetworkSpec)
    filesystem: FilesystemSpec = Field(default_factory=FilesystemSpec)
    target: Literal["leakbox", "compose", "openshell"] = "leakbox"
    kill_levers: List[LeverName] = Field(
        default_factory=lambda: ["gateway_deny", "docker_disconnect", "docker_pause"]
    )


# --- 9.2 event --------------------------------------------------------------


class Event(Contract):
    """One JSONL line on the shared volume. Append-only and hash-chained.

    `prev_sha256` is filled in by ares.events.EventWriter at append time, not by
    the caller, so the chain cannot be forged by a careless producer.
    """

    ts: str = Field(default_factory=iso)
    run_id: str
    trial: int = 0
    variant: str = "A"
    source: str
    kind: EventKind
    severity: Severity
    bait_id: Optional[str] = None
    flaw: Optional[str] = None
    dst_host: Optional[str] = None
    dst_port: Optional[int] = None
    method: Optional[str] = None
    path: Optional[str] = None
    token_match: bool = False
    detail: Dict[str, Any] = Field(default_factory=dict)
    prev_sha256: Optional[str] = None


# --- 9.3 lever interface ----------------------------------------------------


class Run(Contract):
    run_id: str
    trial: int = 0
    variant: str = "A"
    container: Optional[str] = None
    network: str = "labnet"
    events_dir: Optional[str] = None


class LeverResult(Contract):
    name: str
    t: str = Field(default_factory=iso)
    ok: bool
    verified: Optional[bool] = None
    error: Optional[str] = None
    detail: Dict[str, Any] = Field(default_factory=dict)


# --- 9.4 kill record --------------------------------------------------------


class KillVerify(Contract):
    labnet_endpoint: bool
    paused: bool


class KillRecord(Contract):
    run_id: str
    trial: int
    t_fire: str
    rule: str
    levers: List[LeverResult] = Field(default_factory=list)
    t_verified: Optional[str] = None
    ttk_ms: Optional[int] = None
    post_kill_events: int = 0
    verify: Optional[KillVerify] = None
