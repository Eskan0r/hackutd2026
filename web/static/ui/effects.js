/* One-off visual effects built from the real sprite pixels.
 *
 *   DustCanvas  Poyo crumbles to dust, Undertale style: every opaque pixel of
 *               the current frame becomes a particle; rows let go from the
 *               top down, drift on a slight wind and fade to ash grey.
 *   Puff        a little burst of sand squares (landing, dusting off).
 *
 * Both are pure presentation; neither knows anything about the drill.
 */
import { html } from "/static/ui/sprite.js";

const { useEffect, useRef } = React;

const ASH = [216, 208, 200];
const MARGIN = { left: 20, right: 90, top: 50, bottom: 10 };   // room to drift, native px

/**
 * Crumble frame `frame` of the strip `src` (cell w x h), drawn at `k` per
 * native pixel with its top-left at (left, top) px. Calls onDone once every
 * particle has faded.
 */
export function DustCanvas({ src, w, h, frame = 0, k, left, top, onDone }) {
  const ref = useRef(null);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    let raf = 0;
    let alive = true;
    const img = new Image();
    img.onload = () => {
      if (!alive) return;
      const off = document.createElement("canvas");
      off.width = w;
      off.height = h;
      const g = off.getContext("2d", { willReadFrequently: true });
      g.drawImage(img, frame * w, 0, w, h, 0, 0, w, h);
      const data = g.getImageData(0, 0, w, h).data;

      const parts = [];
      let y0 = h;
      let y1 = 0;
      for (let y = 0; y < h; y += 1) {
        for (let x = 0; x < w; x += 1) {
          const i = (y * w + x) * 4;
          if (data[i + 3] < 128) continue;
          parts.push({ x, y, c: [data[i], data[i + 1], data[i + 2]] });
          y0 = Math.min(y0, y);
          y1 = Math.max(y1, y);
        }
      }
      const span = Math.max(1, y1 - y0);
      for (const p of parts) {
        p.delay = ((p.y - y0) / span) * 750 + Math.random() * 140;   // top rows go first
        p.life = 650 + Math.random() * 500;
        p.vx = 14 + Math.random() * 46;                               // the wind blows right
        p.vy = -(6 + Math.random() * 26);
        p.wob = Math.random() * Math.PI * 2;
      }
      const end = parts.reduce((m, p) => Math.max(m, p.delay + p.life), 0);

      const cv = ref.current;
      if (!cv) return;
      const W = w + MARGIN.left + MARGIN.right;
      const H = h + MARGIN.top + MARGIN.bottom;
      cv.width = Math.round(W * k);
      cv.height = Math.round(H * k);
      const ctx = cv.getContext("2d");
      ctx.imageSmoothingEnabled = false;
      const px = Math.max(1, Math.ceil(k));
      const t0 = performance.now();

      const tick = (now) => {
        if (!alive) return;
        const t = now - t0;
        ctx.clearRect(0, 0, cv.width, cv.height);
        for (const p of parts) {
          let x = p.x;
          let y = p.y;
          let a = 1;
          let c = p.c;
          if (t > p.delay) {
            const age = (t - p.delay) / p.life;
            if (age >= 1) continue;
            const s = (t - p.delay) / 1000;
            x += p.vx * s + Math.sin(p.wob + s * 9) * 1.5;
            y += p.vy * s;
            a = 1 - age;
            const m = Math.min(1, age * 1.6);               // colour turns to ash
            c = [0, 1, 2].map((j) => Math.round(p.c[j] + (ASH[j] - p.c[j]) * m));
          }
          ctx.globalAlpha = a;
          ctx.fillStyle = `rgb(${c[0]},${c[1]},${c[2]})`;
          ctx.fillRect(Math.round((x + MARGIN.left) * k), Math.round((y + MARGIN.top) * k), px, px);
        }
        ctx.globalAlpha = 1;
        if (t < end) raf = requestAnimationFrame(tick);
        else doneRef.current?.();
      };
      raf = requestAnimationFrame(tick);
    };
    img.src = src;
    return () => { alive = false; cancelAnimationFrame(raf); };
  }, [src, w, h, frame, k]);

  return html`<canvas ref=${ref} class="dust" aria-hidden="true"
    style=${{ left: `${left - MARGIN.left * k}px`, top: `${top - MARGIN.top * k}px`,
              width: `${(w + MARGIN.left + MARGIN.right) * k}px`,
              height: `${(h + MARGIN.top + MARGIN.bottom) * k}px` }}></canvas>`;
}

const SAND = ["#dcbc91", "#b78e62", "#ecd5b0"];

/** A burst of `n` sand squares from (0,0) of its parent; `k` = pixel size. */
export function Puff({ n = 8, k, spread = 18, rise = 8 }) {
  const bits = [];
  for (let i = 0; i < n; i += 1) {
    const side = i % 2 === 0 ? -1 : 1;
    const dx = side * (spread * (0.4 + Math.random() * 0.6));
    const dy = -(rise * (0.3 + Math.random()));
    bits.push(html`<span key=${i} style=${{
      "--dx": `${dx * k}px`, "--dy": `${dy * k}px`, "--s": `${Math.max(2, Math.round(k * 1.5))}px`,
      "--c": SAND[i % SAND.length], animationDelay: `${Math.random() * 60}ms`,
    }}></span>`);
  }
  return html`<div class="puff" aria-hidden="true">${bits}</div>`;
}
