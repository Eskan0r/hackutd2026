"""Bake Poyo's eight facings from the original art.

    ./.venv/bin/python scripts/make_poyo_sprites.py [--sheet out.png]

Reads web/static/sprites/agent-front.png (pixel art exported at 8x), recovers
the native grid, and writes web/static/sprites/poyo-{S,SE,E,NE,N,NW,W,SW}.png at
native resolution. The browser upscales them with `image-rendering: pixelated`.

How the turn works: every row of the sprite is treated as a slice of a
cylinder around one vertical axis. Turning by theta moves a pixel at surface
angle phi to phi + theta, so the visor and eye slide toward the edge and vanish
round the side, exactly as a turning figure's would. What comes round from the
back is the same silhouette with the face and hoodie front painted over --
the back of a head is fur, the back of a hoodie is navy.

Stdlib only (zlib + struct), so it runs anywhere the repo does.
"""

from __future__ import annotations

import argparse
import math
import struct
import zlib
from functools import reduce
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
SPRITES = ROOT / "web" / "static" / "sprites"
SOURCE = SPRITES / "agent-front.png"

RGBA = Tuple[int, int, int, int]
Pixels = List[List[Optional[RGBA]]]

# --- png ---------------------------------------------------------------------


def read_png(path: Path) -> Tuple[int, int, List[List[RGBA]]]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a png"
    pos, idat, palette, trns = 8, b"", None, None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            assert depth == 8 and interlace == 0, "only 8-bit, non-interlaced"
        elif kind == b"PLTE":
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b"tRNS":
            trns = body
        elif kind == b"IDAT":
            idat += body
    bpp = {2: 3, 3: 1, 6: 4, 0: 1, 4: 2}[ctype]
    raw = zlib.decompress(idat)
    stride = w * bpp
    rows: List[bytearray] = []
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else b if pb <= pc else c
                line[x] = (line[x] + pred) & 255
        rows.append(line)
        prev = line
    out: List[List[RGBA]] = []
    for line in rows:
        row = []
        for x in range(w):
            px = line[x * bpp:(x + 1) * bpp]
            if ctype == 6:
                row.append(tuple(px))
            elif ctype == 2:
                row.append((px[0], px[1], px[2], 255))
            elif ctype == 3:
                r, g, b = palette[px[0]]
                alpha = trns[px[0]] if trns and px[0] < len(trns) else 255
                row.append((r, g, b, alpha))
            elif ctype == 0:
                row.append((px[0], px[0], px[0], 255))
            else:
                row.append((px[0], px[0], px[0], px[1]))
        out.append(row)
    return w, h, out


def write_png(path: Path, pixels: Pixels, scale: int = 1) -> None:
    h, w = len(pixels), len(pixels[0])
    raw = bytearray()
    for y in range(h * scale):
        raw.append(0)
        for x in range(w * scale):
            raw.extend(pixels[y // scale][x // scale] or (0, 0, 0, 0))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w * scale, h * scale, 8, 6, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


# --- native grid -------------------------------------------------------------


def native_grid(w: int, h: int, px: List[List[RGBA]]) -> Pixels:
    """Every run of identical pixels is a multiple of the export block, so the
    GCD of the run lengths is the block; sample each block's centre."""
    runs = []
    for row in px:
        start = 0
        for x in range(1, w + 1):
            if x == w or row[x] != row[x - 1]:
                runs.append(x - start)
                start = x
    block = reduce(math.gcd, runs) or 1
    gw, gh = w // block, h // block
    grid: Pixels = []
    for y in range(gh):
        out_row: List[Optional[RGBA]] = []
        for x in range(gw):
            c = px[y * block + block // 2][x * block + block // 2]
            out_row.append(c if c[3] >= 128 else None)
        grid.append(out_row)
    return trim(grid)


def trim(grid: Pixels) -> Pixels:
    ys = [y for y, row in enumerate(grid) if any(row)]
    xs = [x for row in grid for x, c in enumerate(row) if c]
    y0, y1, x0, x1 = min(ys), max(ys), min(xs), max(xs)
    return [row[x0:x1 + 1] for row in grid[y0:y1 + 1]]


# --- the turn ----------------------------------------------------------------

HEX = lambda s: (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 255)  # noqa: E731
OUTLINE = HEX("#261432")
FUR = HEX("#c482e2")
FUR_SHADE = HEX("#ba76ce")
NAVY = HEX("#1a1e52")

# Colours that only exist on Poyo's front: visor, its glass, clasp, strings.
VISOR = {HEX("#46286e"), HEX("#b078f6"), HEX("#dcbeff")}
FRONT_TRIM = {HEX("#96baf0"), HEX("#6e8ce2"), HEX("#e6a05a"), HEX("#3c4c9c")}
CLASP = HEX("#e6a05a")

Box = Tuple[int, int, int, int]


def back_colour(grid: Pixels, x: int, y: int, face: Box, chest: Box) -> Optional[RGBA]:
    """What the back of the body looks like at the point mirroring (x, y)."""
    c = grid[y][x]
    if c is None:
        return None
    fx0, fy0, fx1, fy1 = face
    if fx0 <= x <= fx1 and fy0 <= y <= fy1 and (c in VISOR or c == OUTLINE):
        return FUR if (x + y) % 7 else FUR_SHADE
    cx0, cy0, cx1, cy1 = chest
    if cx0 <= x <= cx1 and cy0 <= y <= cy1 and (c in FRONT_TRIM or c == OUTLINE):
        return NAVY
    return c


def feature_boxes(grid: Pixels) -> Tuple[Box, Box]:
    """Locate the face and hoodie front from the art itself, so a redraw of
    agent-front.png does not need these boxes edited by hand."""
    vis = [(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c in VISOR]
    vx0, vx1 = min(p[0] for p in vis), max(p[0] for p in vis)
    vy0, vy1 = min(p[1] for p in vis), max(p[1] for p in vis)
    # the eye and mouth sit right of the visor, on the same band of the head
    face = (vx0 - 1, vy0 - 3, vx1 + 10, vy1 + 2)
    clasp = [(x, y) for y, row in enumerate(grid) for x, c in enumerate(row) if c == CLASP]
    kx = sum(p[0] for p in clasp) // max(1, len(clasp))
    ky = min(p[1] for p in clasp) if clasp else vy1 + 6
    chest = (kx - 7, ky - 4, kx + 7, ky + 16)
    return face, chest


DEPTH = 0.6      # body is this deep relative to its width: profiles are slimmer
SUB = 4          # sub-samples per source pixel, so splatting leaves no holes


def turn(grid: Pixels, theta: float) -> Pixels:
    """Each row is an elliptical slice (half-width a, half-depth b) around one
    vertical axis. Every source pixel is a point on the front of that slice and,
    mirrored, a point on the back; rotate both and keep whichever is nearer the
    viewer per output column (a one-row depth buffer)."""
    h, w = len(grid), len(grid[0])
    opaque = [(x, y) for y in range(h) for x in range(w) if grid[y][x]]
    cx = sum(p[0] for p in opaque) / len(opaque) + 0.5
    reach = [0.0] * h
    for x, y in opaque:
        reach[y] = max(reach[y], abs(x + 0.5 - cx) + 0.5)
    face, chest = feature_boxes(grid)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    out: Pixels = [[None] * w for _ in range(h)]
    for y in range(h):
        a = reach[y]
        if a <= 0:
            continue
        b = a * DEPTH
        zbuf = [-math.inf] * w
        for x in range(w):
            front = grid[y][x]
            if front is None or is_silhouette_edge(grid, x, y):
                # the old outline would become the side of the body facing
                # the viewer -- a dark seam down a profile. Re-inked below.
                continue
            back = back_colour(grid, x, y, face, chest)
            for k in range(SUB):
                u = x + (k + 0.5) / SUB - cx
                phi = math.asin(max(-1.0, min(1.0, u / a)))
                for ang, colour in ((phi, front), (math.pi - phi, back)):
                    sx, sz = a * math.sin(ang), b * math.cos(ang)
                    rx = sx * cos_t + sz * sin_t
                    rz = -sx * sin_t + sz * cos_t
                    ox = int(math.floor(cx + rx))
                    if 0 <= ox < w and rz > zbuf[ox]:
                        zbuf[ox] = rz
                        out[y][ox] = colour
    return outline(out)


def is_silhouette_edge(grid: Pixels, x: int, y: int) -> bool:
    if grid[y][x] != OUTLINE:
        return False
    h, w = len(grid), len(grid[0])
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if not (0 <= nx < w and 0 <= ny < h) or grid[ny][nx] is None:
            return True
    return False


def outline(grid: Pixels) -> Pixels:
    """Wherever the turn exposed a fresh silhouette edge, ink it."""
    h, w = len(grid), len(grid[0])
    out = [row[:] for row in grid]
    for y in range(h):
        for x in range(w):
            if grid[y][x] is None:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < w and 0 <= ny < h) or grid[ny][nx] is None:
                    out[y][x] = OUTLINE
                    break
    return out


def mirror(grid: Pixels) -> Pixels:
    return [row[::-1] for row in grid]


# Facing -> turn angle. The source art faces the viewer (S); turning toward
# screen-right brings the face round to the right edge. E stops short of a true
# 90-degree profile, as 8-bit side views do: a dead profile of a wrapped flat
# drawing is mostly smeared edge pixels, and the face should still peek round.
ANGLES = {"S": 0.0, "SE": math.radians(40), "E": math.radians(72),
          "NE": math.radians(130), "N": math.pi}
MIRRORS = {"SW": "SE", "W": "E", "NW": "NE"}
ORDER = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sheet", type=Path, help="also write a 4x contact sheet here")
    args = ap.parse_args()

    base = native_grid(*read_png(SOURCE))
    frames: Dict[str, Pixels] = {d: turn(base, a) for d, a in ANGLES.items()}
    frames["S"] = base                        # the original, untouched
    for d, src in MIRRORS.items():
        frames[d] = mirror(frames[src])
    for d, f in frames.items():
        write_png(SPRITES / ("poyo-%s.png" % d), f)
    print("wrote %d sprites %dx%d to %s" % (len(frames), len(base[0]), len(base), SPRITES))

    if args.sheet:
        gap = 4
        fw, fh = len(base[0]), len(base)
        sheet: Pixels = [[(250, 236, 180, 255)] * ((fw + gap) * 8) for _ in range(fh)]
        for i, d in enumerate(ORDER):
            for y in range(fh):
                for x in range(fw):
                    c = frames[d][y][x]
                    if c:
                        sheet[y][i * (fw + gap) + x] = c
        write_png(args.sheet, sheet, scale=4)
        print("sheet:", args.sheet)


if __name__ == "__main__":
    main()
