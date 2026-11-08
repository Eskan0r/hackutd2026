# Brev VM Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the whole Ares stack (lab, gateway, defender, CLI, dashboard) on one NVIDIA Brev VM paid from the team's $60 credit, with the sandbox under gVisor, so every teammate's branch can be exercised on the same machine before the demo.

**Architecture:** ARCHITECTURE.md §3 already decides this: one Ubuntu cloud VM runs everything; laptops are SSH and browser clients. Brev "VM Mode" is that VM (full Ubuntu, Docker + Compose preinstalled, `ubuntu` user with sudo, `/home/ubuntu/workspace` persists across stops). We add one idempotent bootstrap script, one compose toggle so `runtime: runsc` is on for the VM and off for Docker Desktop, an env template, and a deploy doc. Nothing in the kill path or the lab changes.

**Tech Stack:** Brev CLI + web console, Ubuntu (22.04 or 24.04, whichever VM Mode provides), Docker Compose v2, gVisor `runsc` from the gVisor apt repo, Python 3.12 venv.

**Spec:** No separate spec; the user skipped brainstorming. The design is the short section below plus ARCHITECTURE.md §3, §7, §12 and the "Infra" rows of the services table.

## Design (decisions made for this plan)

- **Brev over raw AWS.** Brev runs on AWS/GCP underneath, but bills the free credit and needs no cloud account. Decision: Brev VM Mode, cheapest instance the console offers (the CLI's default is a T4; a GPU is wasted here because the model is remote NIM, so pick the smallest option the console shows). Stop the instance between sessions; stopped instances cost nothing and keep the workspace, apt packages and Docker images.
- **One VM, team-shared.** Clone the repo once at `/home/ubuntu/workspace/hackutd2026`. Each teammate checks out their own branch in their own clone under the same workspace if they need isolation (`git worktree` works too). Only the gateway holds `NVIDIA_API_KEY`, in `.env` (repo root), which is gitignored.
- **gVisor toggle by env var, not by editing compose.** `runtime: ${ARES_SANDBOX_RUNTIME:-runc}` on the sandbox service. Docker Desktop keeps working with no env set; the VM sets `ARES_SANDBOX_RUNTIME=runsc` in `.env` (repo root). If `runsc` fails on the Brev image, unset it and the documented runc fallback (§12) applies, and the slide says so.
- **Dashboard stays bound to loopback.** Teammates reach it with `brev port-forward <instance> --port 8090:8090`; judges get a Brev tunnel URL (Cloudflare-authenticated) from the console. The gateway admin port is already `127.0.0.1:8081` and stays that way. No port is opened to the public internet.
- **Out of scope (non-goals):** the host iptables `DOCKER-USER` LOG+DROP rule (§7, not built anywhere yet), the GitHub self-hosted runner, DNS sinkhole, OpenShell, and merging the drill/github-pr/web-app branches. This plan makes main run on the VM; the merges land on top.

## Global Constraints

- Code stays Python 3.9-compatible; the venv is Python 3.12 (CLAUDE.md).
- `labnet` and `sandboxnet` stay `internal: true`; the sandbox keeps `cap_drop: [ALL]`, `no-new-privileges`, no Docker socket, no host mounts (§7). The compose change touches one line of the sandbox service and nothing else.
- Real keys live only in the gateway's host environment (`.env` (repo root)), never in the repo, never in the sandbox.
- `ARES_ADMIN_TOKEN` has no default; compose refuses to start without it. The bootstrap script generates one into `.env` (repo root) only if the file does not exist.
- Nothing attempts a real sandbox escape; `runsc` is a hardening measure, not a test target.
- Tests stay hermetic: `./.venv/bin/python -m pytest tests/ -q` needs no Docker, no network, no key.
- `ARCHITECTURE.md` is updated in the same change where this plan contradicts it (the Azure row).

## Review Focus

1. **`runsc` installed but Docker fails to restart** because `/etc/docker/daemon.json` already had content on the Brev image. Expected: the script preserves existing keys (`runsc install` merges) and prints the `journalctl -u docker` hint instead of leaving Docker down. Pinned by Task 2 step 5 (`bash -n`) and the manual check in Task 4 step 3.
2. **Bootstrap re-run** on an already bootstrapped VM. Expected: no error, no duplicate apt sources, `.env` (repo root) untouched. Pinned by Task 4 step 6.
3. **`ARES_SANDBOX_RUNTIME` unset on Docker Desktop.** Expected: compose resolves to `runc`, selftests pass as before. Pinned by Task 1's test and Task 1 step 6.
4. **Ubuntu 22.04 image (python3.10 only).** Expected: the script installs `python3.12` from deadsnakes and the venv is 3.12. Pinned by Task 4 step 4 (`.venv/bin/python --version`).
5. **Dashboard accidentally public.** Expected: `ARES_WEB_HOST` stays `127.0.0.1`; `.env.example` does not set it; DEPLOY.md tells people to use port-forward or a tunnel. Pinned by Task 3's doc wording and Task 4 step 8.

---

### Task 1: gVisor runtime toggle in compose

**Files:**
- Modify: `lab/docker-compose.yml:148-150` (the commented `# runtime: runsc` under the sandbox service)
- Test: `tests/test_lab_constraints.py`

**Interfaces:**
- Produces: env var `ARES_SANDBOX_RUNTIME` (values `runc` default, `runsc` on the VM), read by compose interpolation. Task 2's `.env.example` and Task 3's docs use this exact name.

- [ ] **Step 1: Write the failing test** in `tests/test_lab_constraints.py`, next to the existing compose checks:

```python
def test_sandbox_runtime_is_an_env_toggle_defaulting_to_runc():
    compose = yaml.safe_load(open(os.path.join(ROOT, "lab", "docker-compose.yml")))
    assert compose["services"]["sandbox"]["runtime"] == "${ARES_SANDBOX_RUNTIME:-runc}"
```

The file has no path helper: define `ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` at module level and add `import yaml` (pyyaml is in requirements).

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv/bin/python -m pytest tests/test_lab_constraints.py -q -k runtime`
Expected: FAIL with `KeyError: 'runtime'`

- [ ] **Step 3: Replace the commented line in `lab/docker-compose.yml`**

Replace the two comment lines ending in `# runtime: runsc` with:

```yaml
    # gVisor per §7. Docker Desktop has no runsc, so the default is plain runc with
    # caps dropped (§12). On the Linux VM set ARES_SANDBOX_RUNTIME=runsc in lab/.env.
    runtime: ${ARES_SANDBOX_RUNTIME:-runc}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `./.venv/bin/python -m pytest tests/ -q`
Expected: all pass (one more than before).

- [ ] **Step 5: Confirm compose still resolves on this Mac**

Run: `cd lab && ARES_ADMIN_TOKEN=x docker compose config 2>/dev/null | grep -A0 "runtime:"`
Expected: `runtime: runc`. (If Docker Desktop is not running, skip and note it; the test in step 1 covers the file.)

- [ ] **Step 6: Commit**

```bash
git add lab/docker-compose.yml tests/test_lab_constraints.py
git commit -m "feat(lab): ARES_SANDBOX_RUNTIME toggles gVisor on the VM, runc elsewhere"
```

### Task 2: VM bootstrap script and env template

**Files:**
- Create: `scripts/vm_bootstrap.sh`
- Create: `.env.example`

**Interfaces:**
- Consumes: `ARES_SANDBOX_RUNTIME` from Task 1.
- Produces: `scripts/vm_bootstrap.sh` (run as `ubuntu` on the VM from the repo root, idempotent) and `.env` (repo root) (created from the example on first run, with a generated `ARES_ADMIN_TOKEN`). Task 3's docs and Task 4's checks call these by name.

- [ ] **Step 1: Write `.env.example`**

```bash
# Copied to lab/.env by scripts/vm_bootstrap.sh (gitignored). Compose reads it.
ARES_ADMIN_TOKEN=            # filled in by the bootstrap script (openssl rand -hex 16)
NVIDIA_API_KEY=              # the only real key; lives here and nowhere else
ARES_SANDBOX_RUNTIME=runsc   # gVisor on the VM; unset or runc on Docker Desktop
ARES_MODEL=nvidia/nemotron-3-super-120b-a12b
```

- [ ] **Step 2: Write `scripts/vm_bootstrap.sh`** with `set -euo pipefail`, run from the repo root, doing in order:

1. Refuse unless `lsb_release -is` is `Ubuntu`; print the release.
2. Docker: if `docker compose version` fails, install `docker.io docker-compose-v2` via apt and `usermod -aG docker "$USER"`, then tell the user to re-login. (Brev VM Mode preinstalls Docker; this branch is the fallback.)
3. gVisor: if `command -v runsc` is missing, add the gVisor apt repo exactly as https://gvisor.dev/docs/user_guide/install/ documents (keyring to `/usr/share/keyrings/gvisor-archive-keyring.gpg`, source list `/etc/apt/sources.list.d/gvisor.list`), `apt-get install -y runsc`. Then, if `docker info --format '{{json .Runtimes}}'` does not contain `runsc`, run `sudo runsc install && sudo systemctl restart docker`; on restart failure print `sudo journalctl -u docker -n 50 --no-pager` and exit 1.
4. Python: if `python3.12` is missing, add `ppa:deadsnakes/ppa` and install `python3.12 python3.12-venv`. Create `.venv` with `python3.12 -m venv .venv` if absent; `./.venv/bin/python -m pip install -q -r requirements.txt`.
5. Env: if `.env` (repo root) is absent, `cp .env.example lab/.env` and replace the empty `ARES_ADMIN_TOKEN=` with `ARES_ADMIN_TOKEN=$(openssl rand -hex 16)` using `sed -i`. Never overwrite an existing `.env` (repo root).
6. Print a summary: Ubuntu release, Docker version, `runsc` present yes/no, venv Python version, and the reminder `put NVIDIA_API_KEY in lab/.env`.

`shortcut: deadsnakes is a third-party PPA; drop step 4's PPA branch once the Brev image is confirmed to be 24.04`.

- [ ] **Step 3: Make it executable and syntax-check**

Run: `chmod +x scripts/vm_bootstrap.sh && bash -n scripts/vm_bootstrap.sh && echo OK`
Expected: `OK`

- [ ] **Step 4: Confirm `.env` is ignored and the example is not**

Run: `git check-ignore -q lab/.env && echo ignored; git check-ignore -q .env.example || echo tracked`
Expected: `ignored` then `tracked`

- [ ] **Step 5: Pyflakes gate still clean**

Run: `./.venv/bin/python -m pyflakes ares/ gateway/ agent/ tests/ scripts/`
Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add scripts/vm_bootstrap.sh .env.example
git commit -m "feat(scripts): idempotent Brev VM bootstrap: gVisor, python3.12 venv, lab/.env"
```

### Task 3: Deploy doc and ARCHITECTURE update

**Files:**
- Create: `docs/DEPLOY.md`
- Modify: `ARCHITECTURE.md` (services table row `Microsoft Azure (GitHub Student Pack)`)
- Modify: `README.md` "Setup" section (one pointer line)

**Interfaces:**
- Consumes: `scripts/vm_bootstrap.sh`, `.env` (repo root), `ARES_SANDBOX_RUNTIME`.

- [ ] **Step 1: Write `docs/DEPLOY.md`** covering, in this order, with exact commands:

1. **Create the instance** (web console, once): Compute → Create a cloud instance → VM Mode → pick the smallest/cheapest instance listed (no GPU needed; the model is remote). Name it `ares-lab`. Note the hourly rate shown on the card.
2. **Local CLI**: `sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/brevdev/brev-cli/main/bin/install-latest.sh)" && brev login`, then `brev shell ares-lab`.
3. **Bootstrap** on the VM: `cd ~/workspace && git clone <repo url> hackutd2026 && cd hackutd2026 && scripts/vm_bootstrap.sh`, then edit `.env` (repo root) to add `NVIDIA_API_KEY`.
4. **Prove it**: the four checks from Task 4 steps 3–7, copied verbatim with expected output.
5. **Reach the dashboard**: `brev port-forward ares-lab --port 8090:8090` for yourself; console → Access → Using Tunnels → port `8090` for a judge link (first open needs a browser login). The web server stays on `127.0.0.1`; do not set `ARES_WEB_HOST=0.0.0.0`. (The dashboard is on the `web-app` branch until merged.)
6. **Cost hygiene**: `brev stop ares-lab` when done; `brev start ares-lab` resumes with everything intact. Deleting is irreversible. Rotate `NVIDIA_API_KEY` after the event.
7. **Fallback**: if `runsc` will not start a container, set `ARES_SANDBOX_RUNTIME=runc` in `.env` (repo root) and say "runc + dropped caps" on the slide (§12).

- [ ] **Step 2: Update the Azure row in `ARCHITECTURE.md`** to:

`| NVIDIA Brev (VM Mode) | The VM | $60 team credit, billed hourly while running | Ubuntu, Docker + Compose preinstalled; smallest instance, no GPU needed; stop between sessions. Setup in docs/DEPLOY.md |`

and in the §3 Infra row that says `Ubuntu 24.04 cloud VM`, change to `Ubuntu cloud VM (Brev VM Mode; 22.04 or 24.04)`.

- [ ] **Step 3: Add one line to README.md Setup**: `Running it on the team VM: see [docs/DEPLOY.md](docs/DEPLOY.md).`

- [ ] **Step 4: Check the doc has no secrets and the links resolve**

Run: `grep -nE "nvapi-|sk-|[0-9a-f]{32}" docs/DEPLOY.md ARCHITECTURE.md README.md; ls docs/DEPLOY.md scripts/vm_bootstrap.sh .env.example`
Expected: grep prints nothing; ls lists all three files.

- [ ] **Step 5: Commit**

```bash
git add docs/DEPLOY.md ARCHITECTURE.md README.md
git commit -m "docs: Brev VM deployment guide; ARCHITECTURE points the VM at Brev"
```

### Task 4: Bring up the VM and prove the stack (manual, needs the Brev account)

**Files:** none in the repo; results go in the PR description.

**Interfaces:**
- Consumes: everything above, pushed to `origin/brev-vm`.

- [ ] **Step 1: Push the branch**: `git push -u origin brev-vm`.

- [ ] **Step 2: Create the instance and run the bootstrap** per `docs/DEPLOY.md` §1–3. Record the Ubuntu release and hourly rate.

- [ ] **Step 3: gVisor is live**

Run on the VM: `docker info --format '{{json .Runtimes}}' | grep -o runsc; docker run --rm --runtime=runsc alpine dmesg | head -1`
Expected: `runsc` and a line starting `[   0.000000] Starting gVisor...`

- [ ] **Step 4: Venv is 3.12 and tests are green**

Run: `./.venv/bin/python --version && ./.venv/bin/python -m pytest tests/ -q`
Expected: `Python 3.12.x`, all tests pass.

- [ ] **Step 5: Leakbox lane under gVisor**

Run: `cd lab && ./selftest.sh`
Expected: last line `PASS: flaws ON leak, flaws OFF hold, no internet, events hash-chained`.

- [ ] **Step 6: Bootstrap is idempotent**

Run: `scripts/vm_bootstrap.sh` a second time; then `grep -c ARES_ADMIN_TOKEN lab/.env`
Expected: exits 0, no apt errors, `1`.

- [ ] **Step 7: Three-lever kill verified on a real Linux Docker**

Run: `./.venv/bin/python -m defender selftest`
Expected: last line `SELFTEST PASSED`; the full-kill case prints `contained=True` with `ttk=` under 1000 ms, the soft_kill case prints `contained=False`.

- [ ] **Step 8: Nothing listens publicly**

Run: `sudo ss -ltnp | grep -vE '127.0.0.1|::1|\[::\]:22|0.0.0.0:22'`
Expected: no Ares ports (8081, 8090) on `0.0.0.0`. Docker-published ports from compose show `127.0.0.1:8081` only.

- [ ] **Step 9: Stop the instance**: `brev stop ares-lab`. Paste the outputs of steps 3–8 into the PR description; open the PR from `brev-vm` into `hosting`.
