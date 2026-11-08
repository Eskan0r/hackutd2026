"""Bake Poyo's chosen frames into the sprite strips the page plays.

    ./.venv/bin/python scripts/bake_poyo.py

Reads the PixelLab runs kept under art/pixellab/, takes the frames picked in
ANIMS below, runs each through pixellab.clean() (palette snapped to the
original art, fringe dropped, detached bits like the idle's halo deleted,
outline re-inked), and writes:

  web/static/sprites/poyo/<anim>.png   one horizontal strip per animation
  web/static/sprites/poyo/poyo.json    cell size, foot anchor, frames, fps

Every strip shares ONE cell size and ONE foot anchor, computed over every
frame of every animation (mirrors included), so switching animation never
makes Poyo jump. Stdlib only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_poyo_sprites import read_png, write_png  # noqa: E402
from pixellab import OUT, clean  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "web" / "static" / "sprites" / "poyo"

Px = Optional[Tuple[int, int, int, int]]
Frame = List[List[Px]]

# name: (run dir, frame indices into that run, mirror, fps, loop)
# Frame picks follow the independent reviews; index 0 is the run's input still.
ANIMS: Dict[str, Tuple[str, List[int], bool, int, bool]] = {
    "idle":   ("idle-s",    [1, 2, 3, 4],    False, 4, True),
    "walk-s": ("walk-s",    [1, 2, 1, 3],    False, 8, True),
    "walk-n": ("walk-n",    [1, 2, 3, 4],    False, 8, True),
    "walk-e": ("walk-e-v2", [0, 1, 3, 4],    False, 10, True),
    "walk-w": ("walk-e-v2", [0, 1, 3, 4],    True, 10, True),
    "sit":    ("sit-s",     [0, 1, 2, 3, 4], False, 8, False),
    "play":   ("play-s",    [1, 2, 3, 4],    False, 5, True),
    "use-s":  ("use-s",     [0, 1, 2, 3, 4], False, 6, True),
    "use-e":  ("use-e",     [0, 2, 3, 2],    False, 6, True),
    "use-w":  ("use-e",     [0, 2, 3, 2],    True, 6, True),
    "panic":  ("panic-s",   [2, 3, 4, 5],    False, 10, True),
    "dust":   ("dust-s",    [1, 2, 3, 4],    False, 6, True),
}

# The shared cell and anchor are measured over these animations only. Adding
# a new animation must never move them -- every strip already baked (and any
# hand fix made to one, like idle.png) depends on that box staying put.
BASE = ["idle", "walk-s", "walk-n", "walk-e", "walk-w", "sit", "play",
        "use-s", "use-e", "use-w", "panic"]


def frame_file(run: str, i: int) -> Path:
    hits = sorted((OUT / run).glob("%02d_*.png" % i))
    if not hits:
        sys.exit("missing frame %d in %s" % (i, OUT / run))
    return hits[0]


def mirror(f: Frame) -> Frame:
    return [row[::-1] for row in f]


def load(name: str) -> List[Frame]:
    run, picks, flip, _, _ = ANIMS[name]
    out = []
    for i in picks:
        f = clean(read_png(frame_file(run, i))[2])
        out.append(mirror(f) if flip else f)
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", metavar="ANIM",
                    help="bake just these animations into the existing cell; "
                         "every other strip (and poyo.json's cell/anchor) is left alone")
    args = ap.parse_args()
    if args.only:
        unknown = [n for n in args.only if n not in ANIMS]
        if unknown:
            sys.exit("unknown animation(s): %s" % ", ".join(unknown))

    frames: Dict[str, List[Frame]] = {name: load(name) for name in BASE}

    # one shared cell: the union of every BASE frame's opaque box
    xs, ys = [], []
    for fl in frames.values():
        for f in fl:
            for y, row in enumerate(f):
                for x, c in enumerate(row):
                    if c:
                        xs.append(x)
                        ys.append(y)
    x0, x1, y0, y1 = min(xs) - 1, max(xs) + 1, min(ys) - 1, max(ys) + 1
    cw, ch = x1 - x0 + 1, y1 - y0 + 1

    # foot anchor: centre of the idle pose's body columns, its lowest row. Not
    # the lowest row's own centre -- that is the tail tip, well off to one side.
    idle = frames["idle"][0]
    ix = [x for row in idle for x, c in enumerate(row) if c]
    foot_y = max(y for y, row in enumerate(idle) for c in row if c)
    anchor = [(min(ix) + max(ix)) // 2 - x0, foot_y - y0]

    DEST.mkdir(parents=True, exist_ok=True)
    manifest_path = DEST / "poyo.json"
    if args.only:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["cell"] != [cw, ch] or manifest["anchor"] != anchor:
            sys.exit("poyo.json cell/anchor %s/%s no longer match the BASE frames (%s/%s); "
                     "refusing to bake into a moved box" % (manifest["cell"], manifest["anchor"], [cw, ch], anchor))
        todo = {name: load(name) for name in args.only}
    else:
        manifest = {"cell": [cw, ch], "anchor": anchor, "anims": {}}
        todo = dict(frames)
        todo.update({name: load(name) for name in ANIMS if name not in frames})

    for name, fl in todo.items():
        clipped = sum(1 for f in fl for y, row in enumerate(f) for x, c in enumerate(row)
                      if c and not (x0 <= x <= x1 and y0 <= y <= y1))
        if clipped:
            print("warning: %s loses %d pixel(s) outside the shared cell" % (name, clipped))
        strip: Frame = [[] for _ in range(ch)]
        for f in fl:
            for y in range(ch):
                strip[y].extend(f[y0 + y][x0:x1 + 1])
        write_png(DEST / (name + ".png"), strip)
        _, _, _, fps, loop = ANIMS[name]
        manifest["anims"][name] = {"frames": len(fl), "fps": fps, "loop": loop}
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("baked %s, cell %dx%d, anchor %s -> %s" % (", ".join(todo), cw, ch, anchor, DEST))


if __name__ == "__main__":
    main()
