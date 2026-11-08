"""ares/events.py must stay importable inside the lab containers.

lab/docker-compose.yml runs the fake services and the policy proxy on bare
`python:3.12-slim` with no pip install, mounting the repo at /src. So anything
they import must be stdlib only. Adding `from ares.contracts import Event` to
ares/events.py would break every lab service at startup -- which is the kind of
thing that shows up as a dead demo, not a failing test, unless it is pinned here.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What the lab image does NOT have.
BLOCKED = ("pydantic", "pydantic_core", "yaml", "httpx", "fastapi", "openai", "uvicorn")

PROBE = textwrap.dedent(
    '''
    import sys, os, tempfile
    BLOCKED = %r

    class LabImageBlocker:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] in BLOCKED:
                raise ImportError(name + " is not installed in the lab image")
            return None

    sys.meta_path.insert(0, LabImageBlocker())
    sys.path.insert(0, %r)

    d = tempfile.mkdtemp()
    os.environ.update(EVENTS_DIR=d, EVENT_SOURCE="proxy", RUN_ID="r_x",
                      TRIAL="1", VARIANT="A")

    from ares.events import emit, verify_chain, read_events

    # The exact call lab/leakbox/proxy.py makes.
    emit("leakbox-proxy", "http", "fire", bait_id=None, flaw="fetch_through",
         dst_host="pkg.acme.test", dst_port=80, method="GET", path="/",
         token_match=False, detail={"decision": "allowed"})

    path = os.path.join(d, "proxy.jsonl")
    assert len(list(read_events(path))) == 1
    assert verify_chain(path) == []
    print("LAB_IMPORT_OK")
    '''
)


def test_events_module_imports_without_any_third_party_package():
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-c", PROBE % (BLOCKED, repo)],
        capture_output=True, text=True, timeout=60,
    )
    assert "LAB_IMPORT_OK" in proc.stdout, (
        "ares/events.py must be stdlib-only.\nstdout: %s\nstderr: %s"
        % (proc.stdout, proc.stderr)
    )


def test_the_blocker_actually_blocks():
    """Guard the guard: if the blocker stopped working the test above is vacuous."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    probe = PROBE % (BLOCKED, repo)
    probe = probe.replace("from ares.events import emit, verify_chain, read_events",
                          "import ares.contracts")
    proc = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode != 0
    assert "not installed in the lab image" in proc.stderr


def test_sandbox_image_does_not_copy_the_ares_package():
    """Section 3: no event-writing code inside the sandbox, by construction."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo, "lab", "sandbox", "Dockerfile")) as fh:
        dockerfile = fh.read()
    copies = [l.strip() for l in dockerfile.splitlines()
              if l.strip().upper().startswith("COPY")]
    assert copies, "no COPY lines found -- did the Dockerfile move?"
    assert not any("ares/" in c for c in copies), (
        "the sandbox image must not contain the ares package: %s" % copies
    )


def test_sandbox_runtime_is_an_env_toggle_defaulting_to_runc():
    with open(os.path.join(ROOT, "lab", "docker-compose.yml")) as f:
        compose = yaml.safe_load(f)
    assert compose["services"]["sandbox"]["runtime"] == "${ARES_SANDBOX_RUNTIME:-runc}"


def test_secrets_template_is_not_under_any_bind_mounted_directory():
    """The real key lives in <repo>/.env; .env.example marks where that is. It
    must not sit under any directory compose bind-mounts into a lab container."""
    lab = os.path.join(ROOT, "lab")
    with open(os.path.join(lab, "docker-compose.yml")) as f:
        compose = yaml.safe_load(f)
    template = os.path.join(ROOT, ".env.example")
    assert os.path.exists(template), "expected the env template at the repo root"
    for name, svc in compose["services"].items():
        for vol in svc.get("volumes", []):
            src = vol.split(":")[0]
            if not src.startswith((".", "/")):
                continue  # a named volume, not a host path
            src = os.path.realpath(os.path.join(lab, src))
            assert os.path.commonpath([src, template]) != src, (
                "%s bind-mounts %s, which would expose .env" % (name, src))
