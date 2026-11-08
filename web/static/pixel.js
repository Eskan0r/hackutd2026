/* Tiny pixel-art toolkit shared by Poyo and the sandbox.
 *
 * Sprites are painted at their native grid into a small offscreen canvas and
 * the browser upscales them with `image-rendering: pixelated`, so edges stay
 * hard at any screen size. Shapes are filled first and the dark outline is
 * derived afterwards, which keeps every sprite's outline one pixel thick and
 * consistent without hand-placing it.
 */

export class Grid {
  constructor(w, h) {
    this.w = w;
    this.h = h;
    this.px = new Array(w * h).fill(null);
  }

  get(x, y) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return null;
    return this.px[y * this.w + x];
  }

  set(x, y, c) {
    x = Math.round(x); y = Math.round(y);
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return;
    this.px[y * this.w + x] = c;
  }

  rect(x, y, w, h, c) {
    for (let j = 0; j < h; j += 1) for (let i = 0; i < w; i += 1) this.set(x + i, y + j, c);
  }

  /* `only`: repaint just pixels already holding that colour (for shading). */
  ellipse(cx, cy, rx, ry, c, only) {
    for (let y = Math.floor(cy - ry); y <= Math.ceil(cy + ry); y += 1) {
      for (let x = Math.floor(cx - rx); x <= Math.ceil(cx + rx); x += 1) {
        const dx = (x + 0.5 - cx) / rx, dy = (y + 0.5 - cy) / ry;
        if (dx * dx + dy * dy > 1) continue;
        if (only !== undefined && this.get(x, y) !== only) continue;
        this.set(x, y, c);
      }
    }
  }

  /* Recolour every pixel of colour `from` that matches a predicate. */
  shade(from, to, pred) {
    for (let y = 0; y < this.h; y += 1)
      for (let x = 0; x < this.w; x += 1)
        if (this.get(x, y) === from && pred(x, y)) this.set(x, y, to);
  }

  outline(c) {
    const add = [];
    for (let y = 0; y < this.h; y += 1) {
      for (let x = 0; x < this.w; x += 1) {
        if (this.get(x, y)) continue;
        if (this.get(x - 1, y) || this.get(x + 1, y) || this.get(x, y - 1) || this.get(x, y + 1))
          add.push([x, y]);
      }
    }
    add.forEach(([x, y]) => this.set(x, y, c));
    return this;
  }

  mirrored() {
    const g = new Grid(this.w, this.h);
    for (let y = 0; y < this.h; y += 1)
      for (let x = 0; x < this.w; x += 1) g.set(this.w - 1 - x, y, this.get(x, y));
    return g;
  }

  toCanvas() {
    const c = document.createElement("canvas");
    c.width = this.w;
    c.height = this.h;
    const g = c.getContext("2d");
    for (let y = 0; y < this.h; y += 1) {
      for (let x = 0; x < this.w; x += 1) {
        const col = this.get(x, y);
        if (!col) continue;
        g.fillStyle = col;
        g.fillRect(x, y, 1, 1);
      }
    }
    return c;
  }
}

/* Deterministic stream so decoration does not twitch between repaints. */
export function rng(seed) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (Math.imul(s, 1103515245) + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}
