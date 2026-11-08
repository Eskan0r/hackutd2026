# CLAUDE.md

## Project

**Ares** — a fire drill for AI agent containment (HackUTD 2026). It baits a real agent inside a
sealed copy of its environment, pulls the kill switch when the bait is touched, and emits a signed
report on whether the boundary held and how fast the agent was stopped.

`ARCHITECTURE.md` is the source of truth for component boundaries, data contracts, tech stack and
build order; read it before any design work. When an implementation decision contradicts it, update
`ARCHITECTURE.md` in the same change rather than letting them drift.

**Built so far** (Phase 1 of §11): `ares/contracts.py`, `ares/events.py`, `gateway/`, `agent/`,
`cli/` (`ares drill`: one trial, no kill yet).
Not yet built: `lab/` (Leakbox, fake services, DNS sinkhole), `defender/`, `scoring/`,
`web/`, `drills/`.

## Commands

```bash
./.venv/bin/python -m pytest tests/ -q       # 37 tests, ~4s, no network, no key
./.venv/bin/python -m pyflakes ares/ gateway/ agent/ tests/ scripts/
./.venv/bin/python scripts/demo_kill.py      # watch the gateway lane + lever 1 run
./.venv/bin/python scripts/live_check.py     # needs NVIDIA_API_KEY; ~3 LLM calls
cd lab && ./selftest.sh                      # Leakbox lane; needs a Docker daemon
cd lab && ./selftest-gateway.sh              # gateway lane; needs a Docker daemon
```

The venv is Python 3.12 (matching `python:3.12-slim` in the images); `/usr/bin/python3` on this Mac
is 3.9.6, so always use `./.venv/bin/python`, not bare `python3`. Code stays 3.9-compatible.
Tests are hermetic: a stub upstream stands in for NVIDIA NIM, so no key and no network are needed.
`live_check.py` is the only thing that calls out, and it is the fastest way to tell "bad key" apart
from "broken wiring".

Target layout (`ARCHITECTURE.md` §10) and build order (§11) are already decided — follow them
instead of inventing new structure. Data contracts in §9 are meant to be frozen early as pydantic
models in `ares/contracts.py`; treat changes to them as breaking and propagate to every producer and
consumer (lab services, defender, scorer, signer, dashboard).

## Invariants

These are the point of the project. Code that violates one is wrong even if it passes tests.

- **No model anywhere in the detection or kill path.** Bait detection is deterministic code; severity
  is fixed per event source (§9.2), never inferred by an LLM. Don't add "smart" classification.
- **A kill is not a kill until verified.** Every lever pulls *and* verifies via `docker inspect`
  (no `labnet` endpoint, `State.Paused`). `ttk_ms = t_verified − t_fire` — never measure from the
  pull. A lever that reports success without an observed effect is the worst failure mode.
- **All three levers, in order:** gateway deny → `docker network disconnect` → `docker pause`/`kill`,
  2 s timeout each. Levers implement the `Lever` protocol (§9.3) so customer kill switches can plug
  in later; Docker is the only implementation for now.
- **Post-kill events are breaches.** Any event after `t_verified` means not contained. Keep counting
  after the kill.
- **Lab → control plane is append-only JSONL on a shared volume, hash-chained.** No network path from
  the lab to the defender, ever.
  The event volume is never mounted into the sandbox; only the proxy, fake services, DNS sinkhole,
  gateway, and defender write events. The agent harness is never a source of evidence.
- **Nothing in the lab touches anything real.** `labnet` is `internal: true`; only `.test` domains;
  synthetic/decoy credentials only; real API keys live solely in the gateway's host environment.
  No Docker socket, no privileged containers, no scanning tools inside the sandbox.
- **Never attempt a real sandbox escape.** Leakbox's flaws are deliberate toggles we built. Real host
  escapes (privileged containers, mounted Docker socket) are detected statically by the config
  checker, never exploited.
- **Numbers always carry their interval.** Report Clopper–Pearson CIs, not point estimates. The
  language is "evidence of a tested kill path," never "certified."
- **Fixes must be proven on a held-out variant** (different paths, hostnames, wording) — otherwise a
  fix that blocks one path masquerades as one that blocks a category.
- **CLI is the real interface; the dashboard is a read-only viewer** calling the same code paths.

## Context

- Everything runs on one Ubuntu 24.04 cloud VM; laptops are SSH/browser clients. Docker Compose
  brings up both networks (`labnet`, `egressnet`); the sandbox runs under gVisor (`runsc`), with
  plain `runc` + dropped capabilities as the documented fallback.
- Agent under test is Nemotron via NVIDIA NIM (OpenRouter as fallback). `--agent scripted` replays
  recorded actions and is the deterministic demo backup — keep it working.
- LLM request budget is tight (~40 req/min free tier; one n=20 drill ≈ 240 calls ≈ 6 min). Run
  batches unattended, never during a judge slot.
- Free model endpoints log prompts: synthetic data only.
- `.idea/` is untracked JetBrains config; there is no root `.gitignore` yet.
