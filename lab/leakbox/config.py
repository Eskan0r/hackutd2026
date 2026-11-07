"""Load leakbox.yaml → (allowlist, flaws). Read fresh per request so toggles apply live.

shortcut: hand-rolled parse of our own fixed-shape config, no PyYAML in the stdlib lab
image; upgrade to PyYAML if the config grows nesting.
"""

import os

CONFIG_PATH = os.environ.get("LEAKBOX_CONFIG", "/src/lab/leakbox.yaml")


def load_leakbox(path: str = CONFIG_PATH) -> tuple[list[str], dict[str, bool]]:
    allowlist: list[str] = []
    flaws: dict[str, bool] = {}
    section = None
    with open(path) as f:
        for raw in f:
            line = raw.split("#", 1)[0].rstrip()
            if not line:
                continue
            if not line[0].isspace():
                section = line.rstrip(":").strip()
                continue
            item = line.strip()
            if section == "allowlist" and item.startswith("- "):
                allowlist.append(item[2:].strip())
            elif section == "flaws":
                key, _, value = item.partition(":")
                flaws[key.strip()] = value.strip().lower() == "true"
    return allowlist, flaws
