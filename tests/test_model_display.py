"""The banner names the model that will run, and the report names the one that did.

It used to print the literal "Nemotron" whenever --model was omitted, which is
every normal run: a family name, identical whichever model the key pointed at.
"""

import subprocess
import sys
from agent import harness
from cli.main import observed_models, resolved_model


def test_the_default_is_the_harness_default_not_a_family_name(monkeypatch):
    """It printed the literal "Nemotron" whenever --model was omitted, which is
    every normal run: it named a family, and said the same thing whichever
    model the key was pointed at."""
    monkeypatch.delenv("ARES_MODEL", raising=False)
    assert resolved_model() == harness.DEFAULT_MODEL
    assert "/" in resolved_model()          # a real id, not a family


def test_ares_model_is_honoured(monkeypatch):
    monkeypatch.setenv("ARES_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    assert resolved_model() == "nvidia/nemotron-3-ultra-550b-a55b"


def test_the_flag_beats_the_environment(monkeypatch):
    monkeypatch.setenv("ARES_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    assert resolved_model("nvidia/nemotron-3.5-bolt-e4b") == "nvidia/nemotron-3.5-bolt-e4b"


def test_observed_models_come_from_the_gateway_not_the_harness():
    """The harness is never a source of evidence (ARCHITECTURE.md section 3),
    so what actually ran is read off the gateway's own llm events."""
    events = [
        {"kind": "llm", "source": "gateway", "detail": {"model": "nvidia/a"}},
        {"kind": "llm", "source": "gateway", "detail": {"model": "nvidia/a"}},
        {"kind": "llm", "source": "gateway", "detail": {"model": "nvidia/b"}},
        {"kind": "http", "source": "leakbox-proxy", "detail": {"model": "ignored"}},
        {"kind": "llm", "source": "gateway", "detail": {}},
    ]
    assert observed_models(events) == ["nvidia/a", "nvidia/b"]


def test_no_llm_events_means_no_claim():
    """A replay makes no model calls; the report must not invent one."""
    assert observed_models([{"kind": "http", "detail": {}}]) == []


def test_the_installed_cli_imports_from_any_directory(tmp_path):
    """`ares` is a console script: it must not need the repo as its cwd.

    cli/main.py imports agent.harness for DEFAULT_MODEL, and `agent` was not in
    pyproject's packages -- so the installed `ares` died with
    ModuleNotFoundError while `pytest` from the repo root passed, because the
    repo root was on sys.path there. Run the import from somewhere else.
    """
    done = subprocess.run(
        [sys.executable, "-c", "import cli.main; print(cli.main.resolved_model())"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    assert "/" in done.stdout            # a real model id came back
