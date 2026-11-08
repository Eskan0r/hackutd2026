#!/usr/bin/env bash
# One-time (and safely re-runnable) setup of the team VM: gVisor runtime for the
# sandbox (ARCHITECTURE.md §7), a Python 3.12 venv for the control plane, and
# lab/.env with a generated admin token. Run as the ubuntu user from the repo root:
#   scripts/vm_bootstrap.sh
# Then put NVIDIA_API_KEY in lab/.env. See docs/DEPLOY.md.
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Ubuntu only: the apt repos below are Ubuntu/Debian specific.
if [ "$(lsb_release -is 2>/dev/null)" != "Ubuntu" ]; then
  echo "vm_bootstrap: expected Ubuntu, got '$(lsb_release -ds 2>/dev/null || uname -s)'" >&2
  exit 1
fi
RELEASE=$(lsb_release -rs)
echo "== Ubuntu $RELEASE"

# 2. Docker + Compose v2. Brev VM Mode preinstalls both; this is the fallback.
if ! docker compose version >/dev/null 2>&1; then
  echo "== installing docker.io + docker-compose-v2"
  sudo apt-get update -q
  sudo apt-get install -y -q docker.io docker-compose-v2
  sudo usermod -aG docker "$USER"
  echo "vm_bootstrap: added $USER to the docker group; log out, back in, and re-run" >&2
  exit 1
fi

# 3. gVisor: install runsc from the gVisor apt repo (https://gvisor.dev/docs/user_guide/install/)
#    and register it with Docker. `runsc install` merges into an existing daemon.json.
if ! command -v runsc >/dev/null 2>&1; then
  echo "== installing runsc"
  sudo apt-get update -q
  sudo apt-get install -y -q apt-transport-https ca-certificates curl gnupg
  curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor --yes -o /usr/share/keyrings/gvisor-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" \
    | sudo tee /etc/apt/sources.list.d/gvisor.list >/dev/null
  sudo apt-get update -q
  sudo apt-get install -y -q runsc
fi
if ! docker info --format '{{json .Runtimes}}' | grep -q runsc; then
  echo "== registering runsc with Docker"
  sudo runsc install
  if ! sudo systemctl restart docker; then
    echo "vm_bootstrap: docker failed to restart after adding runsc; check:" >&2
    echo "  sudo journalctl -u docker -n 50 --no-pager" >&2
    exit 1
  fi
fi

# 4. Python 3.12 venv (matches python:3.12-slim in the images). 24.04 ships 3.12;
#    22.04 ships 3.10, so fall back to deadsnakes.
#    shortcut: deadsnakes is a third-party PPA; drop this branch once the Brev image is confirmed 24.04
if ! command -v python3.12 >/dev/null 2>&1; then
  echo "== installing python3.12 from deadsnakes"
  sudo apt-get install -y -q software-properties-common
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt-get update -q
  sudo apt-get install -y -q python3.12 python3.12-venv
fi
[ -d .venv ] || python3.12 -m venv .venv
./.venv/bin/python -m pip install -q -r requirements.txt

# 5. lab/.env: created once from the example, never overwritten (it holds the real key).
if [ ! -f lab/.env ]; then
  echo "== creating lab/.env"
  cp lab/.env.example lab/.env
  sed -i "s/^ARES_ADMIN_TOKEN=.*/ARES_ADMIN_TOKEN=$(openssl rand -hex 16)/" lab/.env
fi

# 6. Summary.
echo "== done"
echo "   ubuntu:  $RELEASE"
echo "   docker:  $(docker --version)"
echo "   runsc:   $(command -v runsc >/dev/null && echo yes || echo no)"
echo "   venv:    $(./.venv/bin/python --version)"
grep -q '^NVIDIA_API_KEY=$' lab/.env && echo "   next:    put NVIDIA_API_KEY in lab/.env"
