"""Bake the sandbox scene's sprite sheets: the sandcastle and its fire.

    ./.venv/bin/python scripts/make_scene_sprites.py [--sheet out.png]

Writes horizontal strips to web/static/sprites/ (one frame per CELL_W column):

  castle-idle.png   4 frames  flag flutters, a grain of sand drops
  castle-burn.png   3 frames  impact flash -> flames catch -> flames climb
  castle-fire.png   4 frames  looping blaze on the charred castle

Style target is Deltarune overworld art: flat colour areas, a 1px ink line on
every major form, and few frames held long -- the motion comes from timing,
not from frame count. Stdlib only; reuses the PNG writer in make_poyo_sprites.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_poyo_sprites import SPRITES, write_png  # noqa: E402

RGBA = Tuple[int, int, int, int]


def hx(s: str) -> RGBA:
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16), 255)


INK = hx("#1f140e")
# Sand tones come from the hand-drawn mound sprite (art/source/sand-mounds.png):
# its sand, shadow and outline are base, shade and dark here, so the castle,
# the toys' sand and the stage are all one material.
SAND = {"lite": hx("#ecd5b0"), "base": hx("#dcbc91"), "shade": hx("#b78e62"),
        "deep": hx("#8f6a45"), "dark": hx("#553e34")}
CHAR = {"lite": hx("#a8643a"), "base": hx("#7a4428"), "shade": hx("#56301e"),
        "deep": hx("#3a2016"), "dark": hx("#1c0f0b")}
GLOW = {"lite": hx("#ffd98a"), "base": hx("#f2a85a"), "shade": hx("#c9703a"),
        "deep": hx("#8e4526"), "dark": hx("#3a1a10")}
FLAG, FLAG_DARK, POLE = hx("#e5483a"), hx("#a3271f"), hx("#6b4426")
WHITE = hx("#fff8e6")
FIRE = [hx("#c22d23"), hx("#f0761f"), hx("#ffcf3a"), hx("#fff4c0")]   # rim -> core
FIRE_INK = hx("#5e1611")
EMBER = hx("#ffb13b")

CELL_W, CELL_H = 64, 84
GROUND = CELL_H - 3                     # castle sits on this row


class Canvas:
    def __init__(self, w: int = CELL_W, h: int = CELL_H) -> None:
        self.w, self.h = w, h
        self.px: List[List[Optional[RGBA]]] = [[None] * w for _ in range(h)]

    def get(self, x: int, y: int) -> Optional[RGBA]:
        return self.px[y][x] if 0 <= x < self.w and 0 <= y < self.h else None

    def set(self, x: float, y: float, c: Optional[RGBA]) -> None:
        x, y = int(round(x)), int(round(y))
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def rect(self, x0: int, y0: int, x1: int, y1: int, c: RGBA) -> None:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                self.set(x, y, c)

    def block(self, x0: int, y0: int, x1: int, y1: int, pal: Dict[str, RGBA]) -> None:
        """A shaded box with its own ink line: lit left edge, shaded right."""
        self.rect(x0, y0, x1, y1, INK)
        self.rect(x0 + 1, y0 + 1, x1 - 1, y1 - 1, pal["base"])
        self.rect(x0 + 1, y0 + 1, x0 + 1, y1 - 1, pal["lite"])
        self.rect(x1 - 3, y0 + 1, x1 - 1, y1 - 1, pal["shade"])

    def crenels(self, x0: int, x1: int, y: int, pal: Dict[str, RGBA]) -> None:
        x = x0
        while x + 3 <= x1:
            self.block(x, y - 3, x + 3, y, pal)
            x += 5

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, c: RGBA,
                only: Optional[RGBA] = None) -> None:
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if dx * dx + dy * dy <= 1 and (only is None or self.get(x, y) == only):
                    self.set(x, y, c)

    def line(self, x0: float, y0: float, x1: float, y1: float, c: RGBA) -> None:
        n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        for i in range(n + 1):
            t = i / n
            self.set(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, c)


# --- the castle -------------------------------------------------------------

CX = CELL_W // 2
KEEP = (CX - 7, GROUND - 40, CX + 7, GROUND - 18)
LEFT = (CX - 22, GROUND - 31, CX - 11, GROUND - 4)
RIGHT = (CX + 11, GROUND - 31, CX + 22, GROUND - 4)
WALL = (CX - 18, GROUND - 20, CX + 18, GROUND - 4)
TOWER_TOPS = [(CX - 16, LEFT[1] - 3), (CX, KEEP[1] - 3), (CX + 16, RIGHT[1] - 3)]


def ink_silhouette(c: Canvas) -> None:
    edge = []
    for y in range(c.h):
        for x in range(c.w):
            if c.px[y][x] is None:
                continue
            if any(c.get(x + dx, y + dy) is None for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                edge.append((x, y))
    for x, y in edge:
        c.px[y][x] = INK


def castle(pal: Dict[str, RGBA], grain: Optional[int] = None, seed: int = 3) -> Canvas:
    c = Canvas()
    # keep (behind), then the two towers, then the front wall
    c.block(*KEEP, pal)
    c.crenels(KEEP[0], KEEP[2], KEEP[1], pal)
    for t in (LEFT, RIGHT):
        c.block(*t, pal)
        c.crenels(t[0], t[2], t[1], pal)
    c.block(*WALL, pal)
    c.crenels(WALL[0] + 2, WALL[2] - 2, WALL[1], pal)

    # windows and the door arch, in the darkest tone
    for wx, wy in ((LEFT[0] + 4, LEFT[1] + 6), (RIGHT[0] + 4, RIGHT[1] + 6), (CX - 1, KEEP[1] + 5)):
        c.rect(wx, wy, wx + 2, wy + 3, pal["dark"])
        c.set(wx + 1, wy - 1, pal["dark"])
    c.rect(CX - 3, GROUND - 11, CX + 3, GROUND - 4, pal["dark"])
    c.rect(CX - 2, GROUND - 12, CX + 2, GROUND - 12, pal["dark"])

    # the mound it stands in: a wide, flat ellipse with a lit top edge
    for y in range(GROUND - 5, GROUND + 2):
        t = (y - (GROUND - 2)) / 4.0
        half = int(28 * math.sqrt(max(0.0, 1 - t * t)))
        for x in range(CX - half, CX + half + 1):
            if c.get(x, y) is None or y >= GROUND - 3:
                tone = "lite" if y == GROUND - 5 else "shade" if y > GROUND - 1 else "base"
                c.set(x, y, pal[tone])
    ink_silhouette(c)

    # packed-sand texture: a few deliberate dents, not noise
    r = random.Random(seed)
    for _ in range(14):
        x, y = r.randint(CX - 20, CX + 20), r.randint(KEEP[1] + 2, GROUND - 6)
        if c.get(x, y) == pal["base"]:
            c.set(x, y, pal["shade"])
    if grain is not None:
        c.set(LEFT[2] + 2, LEFT[1] + 10 + 2 * grain, pal["deep"])
    return c


FLAG_LENGTHS = [(7, 7, 6, 4), (6, 7, 7, 5), (7, 6, 7, 6), (5, 7, 6, 7)]   # four flutter poses


def flag(c: Canvas, pose: int, burnt: bool = False) -> None:
    px, top = CX, KEEP[1] - 13
    c.rect(px, top, px, KEEP[1] - 4, CHAR["dark"] if burnt else POLE)
    c.set(px, top - 1, INK)
    if burnt:
        return
    lengths = FLAG_LENGTHS[pose]
    for i, n in enumerate(lengths):
        y = top + i
        c.rect(px + 1, y, px + n, y, FLAG if i < 2 else FLAG_DARK)
        c.set(px + n + 1, y, INK)
    c.rect(px + 1, top - 1, px + lengths[0], top - 1, INK)
    c.rect(px + 1, top + 4, px + lengths[3], top + 4, INK)


# --- fire ---------------------------------------------------------------------


def flame(c: Canvas, cx: float, base: int, height: float, width: float, phase: float) -> None:
    """One tongue of fire: nested flat layers (red rim to pale core) with a
    dark-red ink line. Advancing `phase` by pi/2 per frame gives a 4-frame
    flicker that loops."""
    if height < 2:
        return
    layers = [(1.0, 1.0), (0.78, 0.72), (0.55, 0.46), (0.3, 0.22)]
    mask: Dict[Tuple[int, int], int] = {}
    for li, (hs, ws) in enumerate(layers):
        hh = height * hs
        for k in range(int(hh) + 1):
            t = k / max(1.0, hh)                       # 0 at the base, 1 at the tip
            half = width * ws / 2 * (1 - t) ** 0.65 * (1 + 0.18 * math.sin(phase + t * 7))
            sway = math.sin(phase + t * 3.2) * t * 2.2
            y = base - k
            for x in range(int(math.floor(cx + sway - half)), int(math.ceil(cx + sway + half)) + 1):
                mask[(x, y)] = li
    for (x, y), li in mask.items():
        c.set(x, y, FIRE[li])
    for (x, y) in list(mask):
        for dx, dy in ((1, 0), (-1, 0), (0, -1)):
            n = (x + dx, y + dy)
            if n not in mask and c.get(*n) not in FIRE:
                c.set(n[0], n[1], FIRE_INK)


def embers(c: Canvas, frame: int, n: int = 6) -> None:
    r = random.Random(40 + frame)
    for _ in range(n):
        x = r.randint(CX - 24, CX + 24)
        y = r.randint(3, KEEP[1])
        if c.get(x, y) is None:
            c.set(x, y, EMBER)
            if r.random() > 0.5:
                c.set(x, y - 1, FIRE[2])


def blaze(c: Canvas, frame: int, scale: float) -> None:
    ph = frame * math.pi / 2
    (lx, ly), (kx, ky), (rx, ry) = TOWER_TOPS
    flame(c, lx, ly + 3, 15 * scale, 11 * scale, ph)
    flame(c, rx, ry + 3, 15 * scale, 11 * scale, ph + 2.1)
    flame(c, kx, ky + 3, 24 * scale, 15 * scale, ph + 1.0)
    if scale > 0.7:
        # tongues licking out of the windows and the door
        flame(c, LEFT[0] + 5, LEFT[1] + 10, 7 * scale, 4, ph + 0.5)
        flame(c, RIGHT[0] + 5, RIGHT[1] + 10, 7 * scale, 4, ph + 2.6)
        flame(c, CX, GROUND - 5, 9 * scale, 6, ph + 1.7)


def flash() -> Canvas:
    """The impact frame: the castle's silhouette in white inside its ink line,
    the held beat before anything moves."""
    c = castle(SAND)
    flag(c, 0)
    for y in range(c.h):
        for x in range(c.w):
            if c.px[y][x] is not None and c.px[y][x] != INK:
                c.px[y][x] = WHITE
    return c


# --- toys: one per agent tool -------------------------------------------------
#
# Each is a 4-frame idle loop in a TOY x TOY cell, feet on the bottom rows.
# The toy is what the tool does: a bucket fetches (http_get), a watering can
# sends (http_post), a storybook is read (read_file), stacked molds are a
# listing (list_dir), a shovel does the work (run_cmd), a white flag gives up
# (report_blocked).

TOY = 32
TG = TOY - 3                            # toy ground row


def tone(base: str, lite: str, shade: str) -> Dict[str, RGBA]:
    return {"base": hx(base), "lite": hx(lite), "shade": hx(shade)}


BLUE = tone("#4a8fd8", "#8cc0f0", "#2d5f9e")
GREEN = tone("#58bf68", "#92e09c", "#33803f")
RED = tone("#e5483a", "#f27a6e", "#a3271f")
YELLOW = tone("#f3c33c", "#fbe38a", "#c08f1e")
METAL = tone("#d3dae2", "#f4f7fa", "#98a3ae")
PAPER = tone("#fff8e6", "#ffffff", "#e0d2b4")
SHADOW = SAND["shade"]


def toy_canvas() -> Canvas:
    c = Canvas(TOY, TOY)
    return c


def toy_shadow(c: Canvas, w: float = 11) -> None:
    c.ellipse(TOY / 2, TG + 0.5, w, 2.2, SHADOW)


def finish(c: Canvas) -> Canvas:
    """Ink the silhouette, but let the flat shadow stay soft (no line)."""
    edge = []
    for y in range(c.h):
        for x in range(c.w):
            p = c.px[y][x]
            if p is None or p == SHADOW:
                continue
            if any(c.get(x + dx, y + dy) in (None, SHADOW)
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                edge.append((x, y))
    for x, y in edge:
        c.px[y][x] = INK
    return c


def toy_bucket(f: int) -> Canvas:
    c = toy_canvas()
    toy_shadow(c)
    for k in range(13):                                  # tapered body
        y = TG - 1 - k
        inset = (12 - k) // 4
        half = 7 - inset
        c.rect(16 - half - 1, y, 16 + half - 1, y, BLUE["base"])
        c.set(16 - half, y, BLUE["lite"])
        c.rect(16 + half - 3, y, 16 + half - 1, y, BLUE["shade"])
    c.ellipse(15.5, TG - 14, 8.5, 2.4, BLUE["shade"])     # rim
    c.ellipse(15.5, TG - 14, 6.5, 1.4, hx("#3d2513"))     # sand inside
    c.rect(9, TG - 9, 21, TG - 8, BLUE["lite"])           # stripe
    swing = [-1, 0, 1, 0][f]                              # handle sways
    arc(c, 15.5 + swing, TG - 14, 8, 6, METAL["base"])
    return finish(c)


def arc(c: Canvas, cx: float, cy: float, rx: float, ry: float, col: RGBA) -> None:
    """Upper half-ellipse as a solid 1px line (segments, so no gaps)."""
    pts = [(cx + math.cos(math.pi + math.pi * i / 16) * rx,
            cy + math.sin(math.pi + math.pi * i / 16) * ry) for i in range(17)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        c.line(x0, y0, x1, y1, col)


def toy_can(f: int) -> Canvas:
    c = toy_canvas()
    toy_shadow(c)
    c.rect(6, TG - 12, 19, TG - 1, GREEN["base"])         # body
    c.rect(6, TG - 12, 7, TG - 1, GREEN["lite"])
    c.rect(17, TG - 12, 19, TG - 1, GREEN["shade"])
    c.ellipse(12.5, TG - 12, 7, 1.6, GREEN["lite"])
    c.line(19, TG - 5, 27, TG - 13, GREEN["shade"])       # spout
    c.line(19, TG - 4, 27, TG - 12, GREEN["base"])
    c.rect(26, TG - 15, 28, TG - 13, GREEN["lite"])       # rose
    arc(c, 12.5, TG - 13, 5, 4, GREEN["shade"])           # handle
    finish(c)
    drop = [None, TG - 11, TG - 7, TG - 3][f]             # a drop falls
    if drop is not None:
        c.rect(28, drop, 28, drop + 1, hx("#8cc0f0"))
        c.set(28, drop - 1, hx("#ffffff"))
    return c


def toy_book(f: int) -> Canvas:
    c = toy_canvas()
    toy_shadow(c, 12)
    c.rect(5, TG - 6, 26, TG - 1, PAPER["shade"])          # page block
    for x in range(6, 26, 2):
        c.set(x, TG - 3, PAPER["base"])
    c.rect(5, TG - 8, 26, TG - 6, RED["base"])            # back cover lip
    lift = [0, 1, 3, 1][f]                                # the cover flutters
    c.rect(5, TG - 9 - lift, 26, TG - 7 - lift, RED["base"])
    c.rect(5, TG - 9 - lift, 26, TG - 9 - lift, RED["lite"])
    c.rect(14, TG - 9 - lift, 17, TG - 7 - lift, YELLOW["base"])   # clasp
    if lift:
        c.rect(6, TG - 6 - lift, 25, TG - 7, PAPER["lite"])
    return finish(c)


def toy_molds(f: int) -> Canvas:
    c = toy_canvas()
    toy_shadow(c)
    cups = [(RED, 9, 0), (YELLOW, 7, 6), (GREEN, 5, 11)]   # widest at the bottom
    tilt = [0, 1, 0, -1][f]                               # the top one wobbles
    for i, (pal, half, lift) in enumerate(cups):
        dx = tilt if i == 2 else 0
        y1 = TG - 1 - lift
        y0 = y1 - 5
        c.rect(16 - half + dx, y0, 15 + half + dx, y1, pal["base"])
        c.rect(16 - half + dx, y0, 15 + half + dx, y0, pal["lite"])
        c.rect(13 + half + dx, y0 + 1, 15 + half + dx, y1, pal["shade"])
        c.rect(16 - half + dx, y1, 15 + half + dx, y1, INK)
    return finish(c)


def toy_shovel(f: int) -> Canvas:
    c = toy_canvas()
    c.ellipse(16, TG - 1, 12, 3.5, SAND["shade"])          # its mound
    c.ellipse(16, TG - 2, 10, 2.5, SAND["base"])
    c.ellipse(14, TG - 3, 5, 1, SAND["lite"], only=SAND["base"])
    c.rect(15, TG - 22, 17, TG - 9, YELLOW["base"])        # shaft
    c.rect(15, TG - 22, 15, TG - 9, YELLOW["lite"])
    c.rect(11, TG - 25, 21, TG - 22, YELLOW["base"])       # grip
    c.rect(11, TG - 25, 21, TG - 25, YELLOW["lite"])
    c.rect(12, TG - 9, 20, TG - 3, METAL["base"])          # blade
    c.rect(12, TG - 9, 20, TG - 9, METAL["lite"])
    c.rect(19, TG - 8, 20, TG - 3, METAL["shade"])
    finish(c)
    g = [None, 0, 3, 6][f]                                 # a glint sweeps across
    if g is not None:
        c.line(13 + g, TG - 4, 15 + g, TG - 8, hx("#ffffff"))
    return c


def toy_flag(f: int) -> Canvas:
    c = toy_canvas()
    toy_shadow(c, 6)
    c.ellipse(16, TG - 1, 5, 2, SAND["base"])
    c.rect(11, TG - 25, 11, TG - 1, hx("#8a5a2b"))         # stick
    c.rect(12, TG - 25, 12, TG - 1, hx("#6b4426"))
    wave = [(0, 1, 1, 0), (1, 1, 0, 0), (1, 0, 0, 1), (0, 0, 1, 1)][f]
    for i in range(10):                                    # white flag, waving
        y_off = wave[min(3, i // 3)]
        top = TG - 25 + y_off
        c.rect(13 + i, top, 13 + i, top + 7, PAPER["base"])
        c.set(13 + i, top + 7, PAPER["shade"])
    return finish(c)


TOYS = {"toy-get": toy_bucket, "toy-post": toy_can, "toy-read": toy_book,
        "toy-list": toy_molds, "toy-run": toy_shovel, "toy-blocked": toy_flag}


# --- the alarm ---------------------------------------------------------------
#
# A siren that drops in on a metal pole from the top of the screen while the
# castle burns. Two sheets: a 32x8 pole segment the page tiles to any length,
# and the 32x32 siren head that hangs off its end. The pole's columns line up
# in both, so the head joins the pole without a seam. The lamp's bright band
# sweeps round the dome (left, front, right, behind); the page throws the
# matching red beams around the screen.

SIREN_GLOW = hx("#ffe0d8")
POLE_X = (13, 18)                                         # ink..ink, inclusive
POLE_COLS = [INK, METAL["lite"], METAL["base"], METAL["base"], METAL["shade"], INK]


def pole_rows(c: Canvas, y0: int, y1: int) -> None:
    for y in range(y0, y1 + 1):
        for i, col in enumerate(POLE_COLS):
            c.set(POLE_X[0] + i, y, col)


def alarm_pole() -> Canvas:
    c = Canvas(32, 8)
    pole_rows(c, 0, 7)
    c.set(POLE_X[0] + 1, 3, hx("#ffffff"))                  # a glint, so it reads as metal
    return c


def alarm_head(f: int) -> Canvas:
    c = Canvas(32, 32)
    pole_rows(c, 0, 2)
    c.rect(11, 3, 20, 5, METAL["base"])                     # collar
    c.rect(11, 3, 20, 3, METAL["lite"])
    c.rect(18, 4, 20, 5, METAL["shade"])
    c.rect(7, 6, 24, 8, METAL["shade"])                     # mounting plate
    c.rect(7, 6, 24, 6, METAL["base"])
    cx, top = 15.5, 9
    for y in range(top, top + 13):                          # dome, hanging down
        t = (y - top) / 13.0
        half = 7.2 * math.sqrt(max(0.0, 1 - t * t))
        for x in range(int(cx - half + 0.5), int(cx + half + 0.5) + 1):
            c.set(x, y, RED["shade"] if x > cx + half - 2 else RED["base"])
    band = [-4, 0, 4, None][f]                              # the lamp sweeping round
    if band is not None:
        for y in range(top, top + 12):
            for dx in (-1, 0, 1):
                if c.get(int(cx + band) + dx, y) is not None:
                    c.set(int(cx + band) + dx, y, RED["lite"] if dx else SIREN_GLOW)
    c.set(int(cx) - 3, top + 2, hx("#ffffff"))               # dome highlight
    finish(c)
    pole_rows(c, 0, 1)                                      # no ink seam where the pole joins
    return c


# --- the empty sandbox (the stage) -----------------------------------------
#
# Slight top-down, like a Deltarune overworld room: the far and side rails
# show their top faces, the near rail shows its front face too, so the box has
# depth. Rails cast a shadow onto the sand. The sand's texture is the
# hand-drawn mounds below, scattered -- not generated clumps.

STAGE_W, STAGE_H = 512, 288
GRASS = {"base": hx("#6ab04c"), "dark": hx("#4e8f3a"), "lite": hx("#8fd16a"), "deep": hx("#3d7330")}
WOOD = {"top": hx("#d59a52"), "lite": hx("#ecb874"), "base": hx("#b5793c"),
        "shade": hx("#8a5a2b"), "deep": hx("#5e3a19")}
BOX = (28, 30, 484, 258)                 # outer edge of the frame
RAIL = 12                                # rail width seen from above
FRONT = 9                                # near rail's front face height
FLOWERS = [hx("#ffffff"), hx("#f7d14a"), hx("#f29ac2")]

# Recovered at native resolution from art/source/sand-mounds.png (a 14.3x
# upscale): K outline, S sand, o shadow.
MOUNDS = [
    (
        "....KKKK........",
        "...KSSSSK.......",
        ".KSSSSSSSKKKK...",
        ".KSSSSSSSKSSSK..",
        ".KoSSSSoSSSSSSK.",
        ".ooooooooooSooo.",
    ),
    (
        ".......KKKKK.........",
        "......KSSSSKK........",
        "....KSSSSSSSSKKKKK...",
        "..KKKSSSSSSSSKSSSSK..",
        ".KSSooSSSSSSoSSSSSSK.",
        "KoSSSSSSSSSooSSSSooK.",
        ".ooooooooooooooooooo.",
    ),
]
MOUND_PAL = {"K": SAND["dark"], "S": SAND["base"], "o": SAND["shade"]}


def mound(c: Canvas, x: int, y: int, which: int, flip: bool) -> None:
    rows = MOUNDS[which]
    for j, row in enumerate(rows):
        for i, ch in enumerate(row[::-1] if flip else row):
            if ch in MOUND_PAL:
                c.set(x + i, y + j, MOUND_PAL[ch])


def grass_tuft(c: Canvas, x: int, y: int, col: RGBA) -> None:
    for dx, dy in ((0, 0), (-1, -1), (1, -1), (-2, -2), (2, -2)):
        c.set(x + dx, y + dy, col)


MEADOW = 192                             # tile size; it repeats seamlessly


def meadow_tile() -> Canvas:
    """Quiet background grass for pages without the sandbox: tufts, clover,
    a few flowers, two low bushes and a couple of rocks. Everything stays in
    grass tones (outlined in deep grass, not ink) so it reads as backdrop and
    never competes with the sign or Poyo. Draws wrap at the edges, so the
    tile repeats with no seam."""
    c = Canvas(MEADOW, MEADOW)
    c.rect(0, 0, MEADOW - 1, MEADOW - 1, GRASS["base"])
    r = random.Random(77)

    def put(x: float, y: float, col: RGBA) -> None:
        c.set(int(x) % MEADOW, int(y) % MEADOW, col)

    def blob(cx: float, cy: float, rx: float, ry: float, col: RGBA) -> None:
        for y in range(int(cy - ry) - 1, int(cy + ry) + 2):
            for x in range(int(cx - rx) - 1, int(cx + rx) + 2):
                dx, dy = (x + 0.5 - cx) / rx, (y + 0.5 - cy) / ry
                if dx * dx + dy * dy <= 1:
                    put(x, y, col)

    # clover patches: a slightly darker wash, very low contrast
    for _ in range(5):
        cx, cy = r.randint(0, MEADOW), r.randint(0, MEADOW)
        for _ in range(26):
            put(cx + r.randint(-9, 9), cy + r.randint(-5, 5), hx("#62a647"))
    # tufts
    for _ in range(46):
        x, y = r.randint(0, MEADOW), r.randint(0, MEADOW)
        col = GRASS["dark"] if r.random() < 0.75 else GRASS["lite"]
        for dx, dy in ((0, 0), (-1, -1), (1, -1), (-2, -2), (2, -2)):
            put(x + dx, y + dy, col)
    # low bushes: outlined in deep grass, a lit crown, a few berries
    for bx, by, w in ((40, 52, 11), (148, 134, 9)):
        blob(bx + 1, by + 2, w + 1, w * 0.7 + 1, GRASS["deep"])
        blob(bx, by, w, w * 0.7, hx("#5aa040"))
        blob(bx - 2, by - 2, w * 0.6, w * 0.35, hx("#79bf58"))
        for _ in range(3):
            put(bx + r.randint(-w + 3, w - 3), by + r.randint(-2, 3), hx("#c96a5a"))
    # rocks: two small grey-green stones
    for sx, sy in ((112, 40), (24, 160)):
        blob(sx + 1, sy + 1, 5, 3, GRASS["deep"])
        blob(sx, sy, 4.5, 2.6, hx("#9aa58a"))
        put(sx - 2, sy - 1, hx("#b9c2a8"))
        put(sx - 1, sy - 1, hx("#b9c2a8"))
    # a handful of tiny flowers
    for _ in range(9):
        x, y = r.randint(0, MEADOW), r.randint(0, MEADOW)
        col = FLOWERS[r.randrange(3)]
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            put(x + dx, y + dy, col)
        put(x, y, hx("#f2a23a"))
    return c


def sandbox_stage() -> Canvas:
    c = Canvas(STAGE_W, STAGE_H)
    c.rect(0, 0, STAGE_W - 1, STAGE_H - 1, GRASS["base"])
    r = random.Random(21)
    for _ in range(140):
        x, y = r.randint(2, STAGE_W - 3), r.randint(3, STAGE_H - 2)
        grass_tuft(c, x, y, GRASS["dark"] if r.random() < 0.7 else GRASS["lite"])
    for _ in range(14):
        x, y = r.randint(4, STAGE_W - 5), r.randint(4, STAGE_H - 4)
        col = FLOWERS[r.randrange(3)]
        for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
            c.set(x + dx, y + dy, col)
        c.set(x, y, hx("#f2a23a"))

    x0, y0, x1, y1 = BOX
    # contact shadow on the grass along the near and right rails
    c.rect(x0 + 2, y1 + FRONT + 1, x1 + 2, y1 + FRONT + 3, GRASS["deep"])
    c.rect(x1 + 1, y0 + 4, x1 + 3, y1 + FRONT, GRASS["deep"])

    # sand, with the rails' shadow falling down and right onto it
    sx0, sy0, sx1, sy1 = x0 + RAIL, y0 + RAIL, x1 - RAIL, y1 - RAIL
    c.rect(sx0, sy0, sx1, sy1, SAND["base"])
    c.rect(sx0, sy0, sx1, sy0 + 5, SAND["shade"])
    c.rect(sx0, sy0, sx0 + 4, sy1, SAND["shade"])
    c.rect(sx0, sy0, sx1, sy0 + 1, SAND["deep"])

    # the hand-drawn mounds, scattered without overlapping (dart throwing)
    placed: List[Tuple[int, int, int, int]] = []
    for _ in range(600):
        if len(placed) >= 7:
            break
        which = r.randrange(2)
        mw, mh = len(MOUNDS[which][0]), len(MOUNDS[which])
        x = r.randint(sx0 + 10, sx1 - mw - 6)
        y = r.randint(sy0 + 10, sy1 - mh - 4)
        if any(x < px1 + 14 and x + mw + 14 > px0 and y < py1 + 10 and y + mh + 10 > py0
               for px0, py0, px1, py1 in placed):
            continue
        mound(c, x, y, which, flip=r.random() < 0.5)
        placed.append((x, y, x + mw, y + mh))
    # a few pebbles and shells between them
    for _ in range(10):
        x, y = r.randint(sx0 + 10, sx1 - 10), r.randint(sy0 + 12, sy1 - 8)
        if c.get(x, y) != SAND["base"] or c.get(x + 2, y + 2) != SAND["base"]:
            continue
        c.rect(x, y, x + 2, y + 1, hx("#b8ab92"))
        c.rect(x, y + 2, x + 2, y + 2, hx("#8c7f68"))
        c.set(x, y, hx("#d8ccb4"))
    for _ in range(4):
        x, y = r.randint(sx0 + 10, sx1 - 10), r.randint(sy0 + 12, sy1 - 8)
        if c.get(x, y) != SAND["base"]:
            continue
        c.rect(x, y, x + 2, y + 1, hx("#f7c6c0"))
        c.set(x + 1, y - 1, hx("#f7c6c0"))
        c.set(x + 1, y + 1, hx("#d99a94"))

    # rails: top faces all round, plank seams, then the near rail's front face
    def plank_h(xa: int, xb: int, y: int) -> None:
        c.rect(xa, y, xb, y + RAIL - 1, WOOD["top"])
        c.rect(xa, y, xb, y + 1, WOOD["lite"])
        c.rect(xa, y + RAIL - 2, xb, y + RAIL - 1, WOOD["base"])
        for sx in range(xa + 38, xb - 6, 52):
            c.rect(sx, y + 1, sx, y + RAIL - 2, WOOD["shade"])

    def plank_v(x: int, ya: int, yb: int) -> None:
        c.rect(x, ya, x + RAIL - 1, yb, WOOD["top"])
        c.rect(x, ya, x + 1, yb, WOOD["lite"])
        c.rect(x + RAIL - 2, ya, x + RAIL - 1, yb, WOOD["base"])
        for sy in range(ya + 34, yb - 6, 46):
            c.rect(x + 1, sy, x + RAIL - 2, sy, WOOD["shade"])

    plank_h(x0, x1, y0)
    plank_v(x0, y0, y1)
    plank_v(x1 - RAIL + 1, y0, y1)
    plank_h(x0, x1, y1 - RAIL + 1)
    c.rect(x0, y1 + 1, x1, y1 + FRONT, WOOD["base"])          # near rail front face
    c.rect(x0, y1 + 1, x1, y1 + 1, WOOD["lite"])
    c.rect(x0, y1 + FRONT - 1, x1, y1 + FRONT, WOOD["shade"])
    for sx in range(x0 + 38, x1 - 6, 52):
        c.rect(sx, y1 + 2, sx, y1 + FRONT - 1, WOOD["deep"])
    # corner posts: square caps a touch proud of the rails
    for px, py in ((x0 - 1, y0 - 1), (x1 - RAIL, y0 - 1), (x0 - 1, y1 - RAIL), (x1 - RAIL, y1 - RAIL)):
        c.rect(px, py, px + RAIL + 1, py + RAIL + 1, WOOD["lite"])
        c.rect(px + 2, py + 2, px + RAIL - 1, py + RAIL - 1, WOOD["top"])
        c.set(px + RAIL // 2, py + RAIL // 2, WOOD["deep"])   # nail
    for px in (x0 - 1, x1 - RAIL):                              # post fronts
        c.rect(px, y1 + 2, px + RAIL + 1, y1 + FRONT + 1, WOOD["shade"])

    # one ink line round the whole box: outer edge, inner sand edge
    for x in range(x0 - 1, x1 + 2):
        c.set(x, y0 - 2, INK)
        c.set(x, y1 + FRONT + 1, INK)
    for y in range(y0 - 2, y1 + FRONT + 2):
        c.set(x0 - 2, y, INK)
        c.set(x1 + 2, y, INK)
    for x in range(sx0, sx1 + 1):
        c.set(x, sy0 - 1, INK)
        c.set(x, sy1 + 1, INK)
    for y in range(sy0 - 1, sy1 + 2):
        c.set(sx0 - 1, y, INK)
        c.set(sx1 + 1, y, INK)
    return c


# --- sheets -------------------------------------------------------------------


def strip(frames: List[Canvas]) -> List[List[Optional[RGBA]]]:
    rows: List[List[Optional[RGBA]]] = [[] for _ in range(frames[0].h)]
    for f in frames:
        for y in range(f.h):
            rows[y].extend(f.px[y])
    return rows


def build() -> Dict[str, List[Canvas]]:
    idle = []
    for i in range(4):
        c = castle(SAND, grain=i if i < 3 else None)
        flag(c, i)
        idle.append(c)

    catch = castle(GLOW)
    flag(catch, 1)
    blaze(catch, 0, 0.45)
    climb = castle(GLOW)
    flag(climb, 2, burnt=True)
    blaze(climb, 1, 0.75)
    burn = [catch, climb]                 # no white flash frame: the castle never goes blank

    fire = []
    for i in range(4):
        c = castle(CHAR)
        flag(c, 0, burnt=True)
        blaze(c, i, 1.0)
        embers(c, i)
        fire.append(c)
    out = {"castle-idle": idle, "castle-burn": burn, "castle-fire": fire}
    for name, draw in TOYS.items():
        out[name] = [draw(i) for i in range(4)]
    out["alarm-head"] = [alarm_head(i) for i in range(4)]
    out["alarm-pole"] = [alarm_pole()]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sheet", type=Path, help="also write a 4x preview of every strip here")
    args = ap.parse_args()

    stage = sandbox_stage()
    write_png(SPRITES / "sandbox.png", stage.px)
    print("wrote sandbox.png (%dx%d)" % (STAGE_W, STAGE_H))
    meadow = meadow_tile()
    write_png(SPRITES / "meadow.png", meadow.px)
    print("wrote meadow.png (%dx%d tile)" % (MEADOW, MEADOW))
    if args.sheet:
        write_png(args.sheet.with_name(args.sheet.stem + "-meadow.png"),
                  [row * 2 for row in meadow.px] * 2, scale=2)
    if args.sheet:
        write_png(args.sheet.with_name(args.sheet.stem + "-sandbox.png"), stage.px, scale=2)

    sheets = build()
    for name, frames in sheets.items():
        write_png(SPRITES / (name + ".png"), strip(frames))
        print("wrote %s.png (%d frames of %dx%d)" % (name, len(frames), frames[0].w, frames[0].h))

    if args.sheet:
        bg = (246, 226, 150, 255)
        width = CELL_W * 4
        rows: List[List[Optional[RGBA]]] = []
        toys = [frames for name, frames in sheets.items() if name.startswith("toy-")]
        for name, frames in sheets.items():
            if name.startswith("toy-"):
                continue
            for row in strip(frames):
                rows.append([c or bg for c in row] + [bg] * (width - len(row)))
            rows.extend([[bg] * width for _ in range(4)])
        # toys two to a row: 4 frames of the first, then 4 of the second
        for i in range(0, len(toys), 2):
            pair = toys[i:i + 2]
            band = [sum((strip(fr)[y] for fr in pair), []) for y in range(TOY)]
            for row in band:
                rows.append([c or bg for c in row] + [bg] * (width - len(row)))
            rows.extend([[bg] * width for _ in range(4)])
        write_png(args.sheet, rows, scale=4)
        print("sheet:", args.sheet)


if __name__ == "__main__":
    main()
