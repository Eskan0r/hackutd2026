"""The defender selftest must exercise the same container runtime the sandbox
uses on the VM (gVisor), or a green selftest there proves nothing about runsc."""

from defender.selftest import sandbox_runtime


def test_sandbox_runtime_defaults_to_runc(monkeypatch):
    monkeypatch.delenv("ARES_SANDBOX_RUNTIME", raising=False)
    assert sandbox_runtime() == "runc"


def test_sandbox_runtime_reads_the_compose_toggle(monkeypatch):
    monkeypatch.setenv("ARES_SANDBOX_RUNTIME", "runsc")
    assert sandbox_runtime() == "runsc"
