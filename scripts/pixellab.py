"""Minimal PixelLab API client for generating Poyo's sprites.

    ./.venv/bin/python scripts/pixellab.py balance
    ./.venv/bin/python scripts/pixellab.py reference           # build the 128px input
    ./.venv/bin/python scripts/pixellab.py rotate8 NAME [--desc TEXT]
    ./.venv/bin/python scripts/pixellab.py animate NAME --image PNG --action TEXT [--frames 8]

Reads PIXELLAB_API_TOKEN from the environment or the repo's .env (gitignored);
the token is only ever sent as the Authorization header, never printed.
Every job's raw JSON and every image it returns land in art/pixellab/NAME/,
so no paid generation is ever lost to a parsing bug here.

This is a dev-time asset tool. Nothing in the drill, the lab or the dashboard
calls it, and it sends only Poyo's art -- no drill data, no credentials.
Stdlib only.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_poyo_sprites import SOURCE, native_grid, read_png, write_png  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "art" / "pixellab"
API = "https://api.pixellab.ai/v2"
CANVAS = 128
REFERENCE = OUT / "reference-128.png"


def token() -> str:
    tok = os.environ.get("PIXELLAB_API_TOKEN")
    env = ROOT / ".env"
    if not tok and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PIXELLAB_API_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        sys.exit("PIXELLAB_API_TOKEN is not set (env or .env)")
    return tok


def call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + token(),
        "Content-Type": "application/json",
        "User-Agent": "ares-sprite-tool/1",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:800]
        sys.exit("PixelLab %s %s -> HTTP %d: %s" % (method, path, e.code, detail))


def b64_png(path: Path) -> Dict[str, str]:
    return {"type": "base64", "base64": base64.b64encode(path.read_bytes()).decode(), "format": "png"}


def images_in(obj: Any, trail: str = "") -> Iterator[Tuple[str, bytes]]:
    """Every base64 image anywhere in a response, with the JSON path to it."""
    if isinstance(obj, dict):
        if isinstance(obj.get("base64"), str) and len(obj["base64"]) > 64:
            yield trail or "image", base64.b64decode(obj["base64"])
            return
        for k, v in obj.items():
            yield from images_in(v, (trail + "." if trail else "") + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from images_in(v, "%s[%d]" % (trail, i))


def wait(job_id: str) -> Dict[str, Any]:
    t0 = time.time()
    while True:
        job = call("GET", "/background-jobs/" + job_id)
        status = job.get("status")
        print("  job %s: %s (%.0fs)" % (job_id[:8], status, time.time() - t0))
        if status in ("completed", "failed"):
            return job
        if time.time() - t0 > 600:
            sys.exit("gave up waiting on job " + job_id)
        time.sleep(5)


def save(name: str, response: Dict[str, Any]) -> List[Path]:
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "response.json").write_text(json.dumps(response, indent=1), encoding="utf-8")
    paths = []
    for i, (trail, png) in enumerate(images_in(response)):
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in trail)[-60:]
        p = d / ("%02d_%s.png" % (i, safe))
        p.write_bytes(png)
        paths.append(p)
    usage = response.get("usage") or {}
    print("saved %d image(s) to %s  (cost: %s)" % (len(paths), d, usage.get("usd", "?")))
    return paths


def run_job(name: str, path: str, body: Dict[str, Any]) -> None:
    started = call("POST", path, body)
    job_id = started.get("background_job_id")
    if not job_id:
        save(name, started)
        return
    job = wait(job_id)
    save(name, job)
    if job.get("status") == "failed":
        sys.exit("job failed; see %s" % (OUT / name / "response.json"))


def cmd_reference(_: argparse.Namespace) -> None:
    """Poyo's native grid (63x70) centred on a 128 canvas, feet near the floor.
    Native size, not the 8x export: the model works on the real pixel grid."""
    grid = native_grid(*read_png(SOURCE))
    h, w = len(grid), len(grid[0])
    canvas = [[None] * CANVAS for _ in range(CANVAS)]
    ox, oy = (CANVAS - w) // 2, CANVAS - h - 8
    for y in range(h):
        for x in range(w):
            canvas[oy + y][ox + x] = grid[y][x]
    OUT.mkdir(parents=True, exist_ok=True)
    write_png(REFERENCE, canvas)
    print("reference:", REFERENCE, "(%dx%d sprite on %d canvas)" % (w, h, CANVAS))


def palette() -> List[Tuple[int, int, int, int]]:
    """The original art's own colours -- the only ones a cleaned frame may use."""
    grid = native_grid(*read_png(SOURCE))
    return sorted({c for row in grid for c in row if c})


def largest_component(g: List[List[Optional[Tuple[int, int, int, int]]]]) -> set:
    h, w = len(g), len(g[0])
    seen: set = set()
    best: List[Tuple[int, int]] = []
    for y in range(h):
        for x in range(w):
            if g[y][x] is None or (x, y) in seen:
                continue
            comp, stack = [], [(x, y)]
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                comp.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and g[ny][nx] is not None and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if len(comp) > len(best):
                best = comp
    return set(best)


def clean(px: List[List[Tuple[int, int, int, int]]]) -> List[List[Optional[Tuple[int, int, int, int]]]]:
    """Make a generated frame look hand-placed: drop the anti-alias fringe,
    snap every pixel to the source palette, and re-ink the silhouette with the
    source's 1px outline colour."""
    pal = palette()
    ink = min(pal, key=lambda c: sum(c[:3]))
    h, w = len(px), len(px[0])
    out: List[List[Optional[Tuple[int, int, int, int]]]] = [[None] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[y][x]
            if a < 128:
                continue
            out[y][x] = min(pal, key=lambda c: (c[0] - r) ** 2 * 3 + (c[1] - g) ** 2 * 4 + (c[2] - b) ** 2 * 2)
    # lone pixels left by the fringe
    for y in range(h):
        for x in range(w):
            if out[y][x] and sum(1 for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                                 if 0 <= x + dx < w and 0 <= y + dy < h and out[y + dy][x + dx]) <= 1:
                out[y][x] = None
    # Poyo only: keep the largest connected shape. Generated extras that float
    # free (a halo ring, sweat drops, a thrown visor) go; effects are drawn by
    # the scene in code, where they can be timed and kept on-palette.
    body = largest_component(out)
    out = [[out[y][x] if (x, y) in body else None for x in range(w)] for y in range(h)]
    edge = [(x, y) for y in range(h) for x in range(w) if out[y][x] and any(
        not (0 <= x + dx < w and 0 <= y + dy < h) or out[y + dy][x + dx] is None
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    for x, y in edge:
        out[y][x] = ink
    return out


def cmd_sheet(a: argparse.Namespace) -> None:
    """Tile every frame in art/pixellab/NAME/ side by side, raw on top and
    cleaned below, so a run can be judged before anything is kept."""
    files = sorted((OUT / a.name).glob("[0-9][0-9]_*.png"))
    raw = [read_png(p)[2] for p in files]
    rows = [raw, [clean(f) for f in raw]]
    bg = (246, 226, 150, 255)
    fw, fh = max(len(f[0]) for f in raw), max(len(f) for f in raw)
    sheet = [[bg] * ((fw + 2) * len(raw)) for _ in range((fh + 2) * len(rows))]
    for r, frames in enumerate(rows):
        for i, f in enumerate(frames):
            for y, row in enumerate(f):
                for x, c in enumerate(row):
                    if c and c[3] >= 128:
                        sheet[r * (fh + 2) + y][i * (fw + 2) + x] = c
    target = Path(a.out) if a.out else OUT / (a.name + "-sheet.png")
    write_png(target, sheet, scale=a.scale)
    if a.keep:
        d = OUT / a.name / "clean"
        d.mkdir(exist_ok=True)
        for p, f in zip(files, rows[1]):
            write_png(d / p.name, f)
    print("sheet:", target)


def cmd_balance(_: argparse.Namespace) -> None:
    b = call("GET", "/balance")
    sub = b.get("subscription", {})
    print("usd credits: %s | subscription: %s, %s of %s generations left" % (
        b.get("credits", {}).get("usd"), sub.get("status"), sub.get("generations"), sub.get("total")))


POYO = ("chibi lilac-purple cat creature with big pointed ears, wearing an open navy-blue hoodie "
        "with light-blue drawstrings and an orange clasp, a purple visor over its right eye, "
        "clean dark 1px outline, flat colours")


def cmd_rotate8(a: argparse.Namespace) -> None:
    image = Path(a.image) if a.image else REFERENCE
    run_job(a.name, "/generate-8-rotations-v3", {
        "first_frame": b64_png(image), "description": a.desc or POYO,
        "no_background": True, "seed": a.seed})


def cmd_rotate1(a: argparse.Namespace) -> None:
    """One target direction from a reference, palette forced to the original's
    colours -- for a facing the 8-way batch got wrong."""
    image = Path(a.image) if a.image else REFERENCE
    run_job(a.name, "/rotate", {
        "image_size": {"width": CANVAS, "height": CANVAS},
        "from_image": b64_png(image), "color_image": b64_png(REFERENCE),
        "from_direction": a.src, "to_direction": a.to,
        "from_view": a.view, "to_view": a.view, "seed": a.seed or None})


def cmd_animate(a: argparse.Namespace) -> None:
    body = {"first_frame": b64_png(Path(a.image)), "action": a.action,
            "frame_count": a.frames, "no_background": True, "seed": a.seed}
    run_job(a.name, "/animate-with-text-v3", body)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("balance").set_defaults(fn=cmd_balance)
    sub.add_parser("reference").set_defaults(fn=cmd_reference)
    r = sub.add_parser("rotate8")
    r.add_argument("name")
    r.add_argument("--image")
    r.add_argument("--desc")
    r.add_argument("--seed", type=int, default=0)
    r.set_defaults(fn=cmd_rotate8)
    o = sub.add_parser("rotate1")
    o.add_argument("name")
    o.add_argument("--image")
    o.add_argument("--src", default="south")
    o.add_argument("--to", required=True)
    o.add_argument("--view", default="low top-down")
    o.add_argument("--seed", type=int, default=0)
    o.set_defaults(fn=cmd_rotate1)
    m = sub.add_parser("animate")
    m.add_argument("name")
    m.add_argument("--image", required=True)
    m.add_argument("--action", required=True)
    m.add_argument("--frames", type=int, default=8)
    m.add_argument("--seed", type=int, default=0)
    m.set_defaults(fn=cmd_animate)
    s = sub.add_parser("sheet")
    s.add_argument("name")
    s.add_argument("--out")
    s.add_argument("--scale", type=int, default=2)
    s.add_argument("--keep", action="store_true", help="also write cleaned frames to NAME/clean/")
    s.set_defaults(fn=cmd_sheet)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
