#!/usr/bin/env bash
# One-step setup for Ares. Safe to re-run: it only creates what is missing.
#   ./setup.sh
set -uo pipefail
cd "$(dirname "$0")"

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; }
todo() { printf '  \033[33m!\033[0m %s\n' "$1"; }
ready=1

echo "Ares setup"

# 1. Python 3.12+ (the lab images use 3.12; macOS's built-in python3 is 3.9 and will not work)
PY=""
for c in python3.13 python3.12 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info[:2] < (3, 12))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  bad "Python 3.12 or newer not found. macOS: brew install python@3.12   then re-run ./setup.sh"
  exit 1
fi
ok "Python: $("$PY" --version)"

# 2. Virtualenv + dependencies + the `ares` command
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || { bad "could not create .venv"; exit 1; }
fi
if ./.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt && ./.venv/bin/python -m pip install -q --disable-pip-version-check -e .; then
  ok "Dependencies installed; command: ./.venv/bin/ares"
else
  bad "pip install failed (see the error above)"; exit 1
fi

# 3. .env with the two keys
if [ ! -f .env ]; then
  cp .env.example .env
  ok "Created .env from .env.example"
fi
for key in NVIDIA_API_KEY GITHUB_TOKEN; do
  if grep -Eq "^${key}=.+" .env; then
    ok "$key is set in .env"
  else
    todo "$key is empty in .env"; ready=0
  fi
done

# 4. Docker (the lab runs in containers)
if docker info >/dev/null 2>&1; then
  ok "Docker is running"
else
  todo "Docker is not running: start Docker Desktop"; ready=0
fi

# 5. The test suite (no Docker, no keys, ~6 s)
if ./.venv/bin/python -m pytest tests/ -q >/tmp/ares-setup-tests.log 2>&1; then
  ok "Tests pass ($(tail -1 /tmp/ares-setup-tests.log))"
else
  bad "Tests failed: see /tmp/ares-setup-tests.log"; ready=0
fi

echo
if [ "$ready" = 1 ]; then
  echo "Ready. Next:"
else
  echo "Almost there. Fix the ! items above, then:"
fi
cat <<'EOF'
  1. Keys in .env (no quotes, no spaces around =):
       NVIDIA_API_KEY   build.nvidia.com  (free)
       GITHUB_TOKEN     GitHub > Settings > Developer settings > Fine-grained tokens:
                        only your target repo; Contents + Pull requests = Read and write
  2. Make an empty GitHub repo you own (private is fine), then:
       ./.venv/bin/ares setup-target <you>/<repo>
  3. Run the whole drill (one terminal, about 2 minutes):
       ./.venv/bin/ares drill --target <you>/<repo>
EOF
