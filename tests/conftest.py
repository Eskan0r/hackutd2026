"""Keep tests hermetic: importing cli.drill loads the repo-root .env, so clear real keys before every
test. Tests that need a key set a fake one with monkeypatch."""

import pytest


@pytest.fixture(autouse=True)
def _no_real_keys(monkeypatch):
    for name in ("NVIDIA_API_KEY", "OPENROUTER_API_KEY", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
