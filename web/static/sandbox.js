/* The children's sandbox: background art, toy sprites for project nodes, and
 * the random scatter that places them.
 *
 * Art only. The canvas never draws text (see CLAUDE.md); a node's identity
 * lives in its aria-label, not on screen.
 */
import { Grid, rng } from "/static/pixel.js";

export const SW = 400;
export const SH = 250;
const RAIL = 9;
const MARGIN = 5;

const C = {
  grass: "#6ab04c", grassDark: "#4e8f3a", grassLite: "#7ec45c",
  railLite: "#d59a52", rail: "#b5793c", railDark: "#7a4a21", railEdge: "#4a2a10",
  sand: "#f7dc74", sandDark: "#e3c155", sandDeep: "#c9a338", sandLite: "#fdf0b2",
  pebble: "#b8ab92", pebbleDark: "#8c7f68", shell: "#f7c6c0",
  line: "#3a2414"
};

/** Inner sand rectangle, in native pixels. */
export const SAND = {
  x0: MARGIN + RAIL, y0: MARGIN + RAIL,
  x1: SW - MARGIN - RAIL, y1: SH - MARGIN - RAIL
};

/* Fake company projects. Real ones will come from the drill's config. */
export const PROJECTS = [
  { id: "storefront",   name: "storefront",     toy: "castle", color: "#e2504c", health: "ok" },
  { id: "payments-api", name: "payments-api",   toy: "bucket", color: "#4a8fd8", health: "ok" },
  { id: "auth",         name: "auth-service",   toy: "ball",   color: "#58bf68", health: "warn" },
  { id: "pipeline",     name: "data-pipeline",  toy: "shovel", color: "#f3c33c", health: "ok" },
  { id: "recsys",       name: "ml-recsys",      toy: "star",   color: "#b06ae0", health: "sync" },
  { id: "inventory",    name: "inventory",      toy: "bucket", color: "#49c2b4", health: "ok" },
  { id: "notify",       name: "notifications",  toy: "ball",   color: "#f08a3c", health: "ok" },
  { id: "search",       name: "search",         toy: "castle", color: "#4a8fd8", health: "bad" },
  { id: "billing",      name: "billing-worker", toy: "star",   color: "#e2504c", health: "ok" }
];

const HEALTH = { ok: "#4fd06a", warn: "#f3c33c", bad: "#e2504c", sync: "#5aa8e0" };

// ---------------------------------------------------------------- background

function px(g, x, y, w, h, c) {
  g.fillStyle = c;
  g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

export function drawSandbox(canvas) {
  canvas.width = SW;
  canvas.height = SH;
  const g = canvas.getContext("2d");
  const r = rng(11);

  px(g, 0, 0, SW, SH, C.grass);
  for (let i = 0; i < 120; i += 1) {
    const x = r() * SW, y = r() * SH;
    px(g, x, y, 1, 2, r() > 0.5 ? C.grassDark : C.grassLite);
  }

  // frame
  const fx = MARGIN, fy = MARGIN, fw = SW - 2 * MARGIN, fh = SH - 2 * MARGIN;
  px(g, fx, fy, fw, fh, C.railEdge);
  px(g, fx + 1, fy + 1, fw - 2, fh - 2, C.rail);
  px(g, fx + 2, fy + 2, fw - 4, 2, C.railLite);
  px(g, fx + 2, fy + fh - 4, fw - 4, 2, C.railDark);
  for (let x = fx + 30; x < fx + fw - 10; x += 40) {
    px(g, x, fy + 2, 1, RAIL - 3, C.railDark);
    px(g, x, fy + fh - RAIL + 1, 1, RAIL - 3, C.railDark);
  }
  for (let y = fy + 30; y < fy + fh - 10; y += 40) {
    px(g, fx + 2, y, RAIL - 3, 1, C.railDark);
    px(g, fx + fw - RAIL + 1, y, RAIL - 3, 1, C.railDark);
  }
  [[fx, fy], [fx + fw - RAIL - 1, fy], [fx, fy + fh - RAIL - 1],
   [fx + fw - RAIL - 1, fy + fh - RAIL - 1]].forEach(([x, y]) => {
    px(g, x, y, RAIL + 1, RAIL + 1, C.railEdge);
    px(g, x + 1, y + 1, RAIL - 1, RAIL - 1, C.railLite);
  });

  // sand, with an inner shadow under the top rail
  const { x0, y0, x1, y1 } = SAND;
  px(g, x0, y0, x1 - x0, y1 - y0, C.sand);
  px(g, x0, y0, x1 - x0, 2, C.sandDeep);
  px(g, x0, y0 + 2, x1 - x0, 1, C.sandDark);
  px(g, x0, y0, 2, y1 - y0, C.sandDark);

  // grain
  for (let i = 0; i < 700; i += 1) {
    const x = x0 + 2 + r() * (x1 - x0 - 4), y = y0 + 4 + r() * (y1 - y0 - 6);
    const t = r();
    px(g, x, y, 1, 1, t < 0.45 ? C.sandDark : t < 0.8 ? C.sandLite : C.sandDeep);
  }
  // swirls raked into the sand
  for (let i = 0; i < 6; i += 1) {
    const cx = x0 + 20 + r() * (x1 - x0 - 40), cy = y0 + 16 + r() * (y1 - y0 - 30);
    const rad = 6 + r() * 8;
    for (let a = 0; a < Math.PI * 1.3; a += 0.12) {
      px(g, cx + Math.cos(a + i) * rad, cy + Math.sin(a + i) * rad * 0.55, 1, 1, C.sandDark);
    }
  }
  // small mounds
  for (let i = 0; i < 5; i += 1) {
    const cx = x0 + 16 + r() * (x1 - x0 - 32), cy = y0 + 18 + r() * (y1 - y0 - 26);
    const w = 10 + r() * 10, h = 3 + r() * 2;
    px(g, cx - w / 2, cy, w, 2, C.sandDeep);
    for (let k = 0; k < h; k += 1) {
      const rw = w * (1 - k / h);
      px(g, cx - rw / 2, cy - 1 - k, rw, 1, k > h * 0.5 ? C.sandLite : C.sand);
    }
  }
  // pebbles and shells
  for (let i = 0; i < 14; i += 1) {
    const x = x0 + 6 + r() * (x1 - x0 - 12), y = y0 + 8 + r() * (y1 - y0 - 12);
    if (r() > 0.3) {
      px(g, x, y, 3, 2, C.pebble);
      px(g, x, y + 2, 3, 1, C.pebbleDark);
    } else {
      px(g, x, y, 3, 2, C.shell);
      px(g, x + 1, y - 1, 1, 1, C.shell);
    }
  }
}

// ---------------------------------------------------------------- toys

export const TW = 30;
export const TH = 30;

function shade(c, amt) {
  const n = parseInt(c.slice(1), 16);
  const f = (v) => Math.max(0, Math.min(255, Math.round(v + 255 * amt)));
  const r = f(n >> 16), g = f((n >> 8) & 255), b = f(n & 255);
  return "#" + ((1 << 24) | (r << 16) | (g << 8) | b).toString(16).slice(1);
}

function bucket(g, c) {
  const lite = shade(c, 0.18), dark = shade(c, -0.18);
  for (let y = 0; y < 13; y += 1) {
    const inset = Math.floor(y / 4);
    g.rect(7 + inset, 13 + y, 16 - 2 * inset, 1, y < 2 ? lite : c);
  }
  g.rect(9, 16, 2, 8, lite);
  g.rect(20, 18, 2, 6, dark);
  g.ellipse(15, 13, 8.5, 2, dark);
  g.ellipse(15, 13, 7, 1.2, "#5a3a18");
  // handle
  for (let a = Math.PI; a <= Math.PI * 2; a += 0.12)
    g.set(15 + Math.cos(a) * 8, 12 + Math.sin(a) * 7, "#d3dae2");
}

function castle(g, c) {
  const s = "#f2cf68", sl = "#fbe6a0", sd = "#d4ab45";
  g.rect(6, 15, 18, 11, s);
  g.rect(6, 15, 18, 2, sl);
  g.rect(4, 11, 6, 15, s);
  g.rect(20, 11, 6, 15, s);
  g.rect(4, 11, 6, 1, sl);
  g.rect(20, 11, 6, 1, sl);
  [4, 8, 20, 24].forEach((x) => g.rect(x, 9, 2, 2, s));
  g.rect(13, 20, 4, 6, sd);
  g.rect(14, 19, 2, 1, sd);
  g.rect(7, 14, 1, 2, sd);
  g.rect(22, 14, 1, 2, sd);
  // flag in the project colour
  g.rect(15, 5, 1, 10, "#7a4a21");
  g.rect(16, 5, 5, 3, c);
  g.rect(16, 7, 3, 1, shade(c, -0.15));
}

function ball(g, c) {
  g.ellipse(15, 18, 9, 9, "#f7f2e6");
  g.ellipse(15, 18, 9, 3, c, "#f7f2e6");
  for (let y = 9; y < 28; y += 1)
    for (let x = 6; x < 25; x += 1)
      if (g.get(x, y) === "#f7f2e6" && Math.abs(x - 15) < 3) g.set(x, y, shade(c, 0.1));
  g.ellipse(11.5, 13.5, 2.5, 1.6, "#ffffff");
  g.shade("#f7f2e6", "#d9d2c0", (x, y) => (x - 15) + (y - 18) > 8);
}

function shovel(g, c) {
  g.ellipse(15, 24, 11, 3.5, "#e3c155");
  g.ellipse(15, 23, 9, 2.5, "#fdf0b2");
  g.rect(14, 6, 3, 14, c);
  g.rect(14, 6, 1, 14, shade(c, 0.2));
  g.rect(11, 4, 9, 3, c);
  g.rect(12, 4, 7, 1, shade(c, 0.2));
  g.rect(11, 19, 9, 4, "#c9d1da");
  g.rect(12, 23, 7, 1, "#c9d1da");
  g.rect(11, 19, 9, 1, "#eef2f6");
}

function star(g, c) {
  const pts = [];
  for (let i = 0; i < 10; i += 1) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? 4.6 : 11;
    pts.push([15 + Math.cos(a) * rr, 17 + Math.sin(a) * rr]);
  }
  for (let y = 4; y < 29; y += 1) {
    for (let x = 2; x < 29; x += 1) {
      let inside = false;
      for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i += 1) {
        const [xi, yi] = pts[i], [xj, yj] = pts[j];
        if ((yi > y + 0.5) !== (yj > y + 0.5) &&
            x + 0.5 < ((xj - xi) * (y + 0.5 - yi)) / (yj - yi) + xi) inside = !inside;
      }
      if (inside) g.set(x, y, c);
    }
  }
  g.shade(c, shade(c, 0.2), (x, y) => x + y < 28);
  g.shade(c, shade(c, -0.15), (x, y) => x + y > 38);
}

const TOYS = { bucket, castle, ball, shovel, star };

/** One toy canvas per project; the health light sits in the corner. */
export function buildToy(project) {
  const g = new Grid(TW, TH);
  TOYS[project.toy](g, project.color);
  g.outline(C.line);
  // status beacon, like an Argo health badge without the words
  const hc = HEALTH[project.health];
  g.ellipse(26, 4, 2.6, 2.6, C.line);
  g.ellipse(26, 4, 1.8, 1.8, hc);
  g.set(25, 3, "#ffffff");
  return g.toCanvas();
}

// ---------------------------------------------------------------- scatter

/* Dart-throwing: random spots that keep clear of each other, of the rail, and
 * of Poyo in the middle. Positions are the toy's feet, in native pixels. */
export function scatter(n, seed, keepClear) {
  const r = rng(seed);
  const pad = 18, minGap = 56;
  const out = [];
  for (let tries = 0; out.length < n && tries < 4000; tries += 1) {
    const x = SAND.x0 + pad + r() * (SAND.x1 - SAND.x0 - 2 * pad);
    const y = SAND.y0 + TH + 2 + r() * (SAND.y1 - SAND.y0 - TH - 8);
    const gap = tries > 2500 ? minGap * 0.7 : minGap;
    // toys are anchored at their feet and stand TH tall
    if (keepClear && x > keepClear.x0 - TW / 2 && x < keepClear.x1 + TW / 2 &&
        y > keepClear.y0 && y - TH < keepClear.y1) continue;
    if (out.some((p) => Math.hypot(p.x - x, (p.y - y) * 1.2) < gap)) continue;
    out.push({ x, y });
  }
  return out;
}
