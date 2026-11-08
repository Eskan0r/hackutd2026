"""The dashboard's playback logic, checked under node.

`web/static` has no build step and no npm (CLAUDE.md), so the browser modules
import each other by absolute URL (`/static/ui/stage.js`). node cannot resolve
those, so this copies them into a temp directory, rewrites the prefixes, and
runs tests/js/playback.mjs against the copy.

Why bother at all: play, pause and step-back are implemented as moves of a
single cursor, with `fold(cues, cursor)` deriving the entire scene. That only
works while fold stays pure and reversible. If it stops being either, nothing
throws -- stepping back just quietly stops undoing things, and the page can
end up showing a burning castle for a run whose evidence no longer says so.
That is exactly the class of overclaim tests/test_web.py exists to prevent, so
it gets a test even though it lives in JavaScript.

Skipped, not failed, where node is unavailable: the Python suite is the gate
that must run everywhere, and `pytest -q` is documented as needing no toolchain.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UI = REPO / "web" / "static" / "ui"
VENDOR = REPO / "web" / "static" / "vendor"
SCRIPT = Path(__file__).resolve().parent / "js" / "playback.mjs"

node = shutil.which("node")
pytestmark = pytest.mark.skipif(not node, reason="node is not installed")


def test_playback_contract(tmp_path):
    (tmp_path / "ui").mkdir()
    (tmp_path / "vendor").mkdir()
    for src in UI.glob("*.js"):
        text = src.read_text(encoding="utf-8")
        text = re.sub(r'"/static/ui/', '"./', text)
        text = re.sub(r'"/static/vendor/', '"../vendor/', text)
        (tmp_path / "ui" / src.name).write_text(text, encoding="utf-8")
    shutil.copy(VENDOR / "htm.js", tmp_path / "vendor" / "htm.js")
    shutil.copy(SCRIPT, tmp_path / "check.mjs")

    done = subprocess.run(
        [node, "check.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
