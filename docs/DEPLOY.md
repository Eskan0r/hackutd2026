# Running Ares on the team VM (NVIDIA Brev)

One VM runs everything (ARCHITECTURE.md §3); laptops are SSH and browser clients. The VM
is a Brev "VM Mode" instance: a full Ubuntu machine with Docker and Compose preinstalled,
paid from the team's Brev credit, billed hourly only while it is running.

## 1. Create the instance (web console, once)

1. Brev console → **Compute** → **Create a cloud instance**.
2. Runtime: **VM Mode** (not Container or Compose mode; we bring our own compose file).
3. Instance: the **smallest, cheapest** option listed. No GPU is needed: the agent's model
   is NVIDIA NIM over the network, and nothing here runs on a GPU. Note the hourly rate
   shown on the card.
4. Name: `ares-lab`.

## 2. Local CLI

```bash
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/brevdev/brev-cli/main/bin/install-latest.sh)" && brev login
brev shell ares-lab          # SSH in; the default user is ubuntu
```

## 3. Bootstrap (on the VM, once)

```bash
cd ~/workspace                                   # persists across stop/start
git clone <repo url> hackutd2026 && cd hackutd2026
scripts/vm_bootstrap.sh
```

The script is safe to re-run. It installs gVisor (`runsc`) and registers it with Docker,
makes a Python 3.12 venv, and creates `.env` at the repo root (gitignored, mode 600) with
a generated `ARES_ADMIN_TOKEN`. Then add the one real key:

```bash
nano .env            # NVIDIA_API_KEY=nvapi-...
```

`.env` stays at the repo root on purpose: `lab/` is bind-mounted into the fake and proxy
containers, so a key there would be inside the lab. Compose and every host-side tool
(`selftest-gateway.sh`, `python -m defender ...`, the CLI) read the shell environment, so
load it in each new shell:

```bash
set -a; source .env; set +a
```

## 4. Prove it

```bash
docker info --format '{{json .Runtimes}}' | grep -o runsc      # runsc
docker run --rm --runtime=runsc alpine dmesg | head -1          # [ 0.000000] Starting gVisor...
./.venv/bin/python --version && ./.venv/bin/python -m pytest tests/ -q   # Python 3.12.x, all pass
(cd lab && ./selftest.sh)              # last line: PASS: flaws ON leak, flaws OFF hold, no internet, events hash-chained
(cd lab && ./selftest-gateway.sh)      # gateway lane; with the key loaded this spends a few LLM calls
./.venv/bin/python -m defender selftest   # last line: SELFTEST PASSED (probe container runs under runsc once .env is loaded)
sudo ss -ltnp | grep -vE '127.0.0.1|::1|:22 '   # nothing of ours on 0.0.0.0
```

## 5. Reach the dashboard

The web server (branch `web-app` until merged) listens on `127.0.0.1:8090`. Keep it
there; do **not** set `ARES_WEB_HOST=0.0.0.0`.

- Yourself: `brev port-forward ares-lab --port 8090:8090`, then open http://localhost:8090.
- Judges or teammates: console → the instance → **Access** → **Using Tunnels** → port
  `8090`. The link goes through Cloudflare and asks for a browser login on first open.

The gateway admin port stays on `127.0.0.1:8081` as well. No Ares port is public.

## 6. Cost hygiene

```bash
brev stop ares-lab     # when you are done; stopped = $0, workspace + apt + images kept
brev start ares-lab    # resume
```

Deleting an instance is irreversible. Rotate `NVIDIA_API_KEY` after the event.

## 7. If gVisor will not start a container

Set `ARES_SANDBOX_RUNTIME=runc` in `.env`, re-source it (a value already in the shell wins
over the file), and recreate the sandbox:

```bash
set -a; source .env; set +a
(cd lab && docker compose up -d sandbox)
```

That is the documented fallback: plain runc with all capabilities dropped
(ARCHITECTURE.md §12). Say so on the slide.
