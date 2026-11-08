/* The sandbox scene: props on the sand, Poyo acting out the run, a speech
 * bubble saying what he is doing, and the log console.
 *
 * Poyo's behaviour comes from steps (see director.js): walk to the prop for
 * the tool being called, use it while the bubble explains, then the next
 * beat. A breakout sets the castle on fire and Poyo panics. Visual only --
 * nothing here can act on a drill.
 */
import { html, Sprite, SPRITES, usePoyoManifest } from "/static/ui/sprite.js";
import { demoScript, demoHeader, stepsFromView, runHeader, loadRequestedRun } from "/static/ui/director.js";
import { LogConsole } from "/static/ui/logs.js";

const { useState, useEffect, useRef, useLayoutEffect } = React;

/* Native resolution of the sandbox art; everything is placed in these pixels. */
const STAGE_W = 512;
const STAGE_H = 288;
const POYO_SIZE = 0.6;     // Poyo is drawn at 60% of the stage's pixel scale
const WALK_SPEED = 70;     // stage pixels per second
const SAND = { x0: 64, x1: 448, y0: 96, y1: 240 };   // where Poyo may rest

/* Props, top-left in stage pixels. One toy per agent tool. */
const TOYS = {
  get:     { tool: "http_get",       src: "toy-get",     x: 96,  y: 70 },
  post:    { tool: "http_post",      src: "toy-post",    x: 176, y: 58 },
  read:    { tool: "read_file",      src: "toy-read",    x: 88,  y: 182 },
  list:    { tool: "list_dir",       src: "toy-list",    x: 150, y: 214 },
  run:     { tool: "run_cmd",        src: "toy-run",     x: 300, y: 210 },
  blocked: { tool: "report_blocked", src: "toy-blocked", x: 432, y: 190 },
};
const CASTLE = { x: 360, y: 70, w: 64, h: 84 };
const IGNITE_MS = 1400;    // white flash + flames catching, before the blaze loop
const CASTLE_ANIMS = {
  idle: { src: "castle-idle", frames: 4, fps: 4 },
  burn: { src: "castle-burn", frames: 3, fps: 3 / (IGNITE_MS / 1000), once: true },
  fire: { src: "castle-fire", frames: 4, fps: 8 },
};

/** Scale that fits the whole sandbox inside `ref`'s box (it follows resizes,
 *  including the logs panel opening and closing). */
function useFitScale(ref) {
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    // fill the box; allow up to 12% overhang, which only crops the sandbox
    // art's own grass margin, never a prop
    const fit = () => {
      const sx = el.clientWidth / STAGE_W;
      const sy = el.clientHeight / STAGE_H;
      const contain = Math.min(sx, sy);
      setScale(Math.max(0.1, Math.min(Math.max(sx, sy), contain * 1.12)));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return scale;
}

/** Where Poyo stands to use a prop, and which way he faces. */
function standPoint(id, from) {
  const p = id === "castle" ? { ...CASTLE } : { ...TOYS[id], w: 32, h: 32 };
  const cx = p.x + p.w / 2;
  const gap = id === "castle" ? 40 : 24;
  const left = from.x <= cx;
  return { x: left ? cx - gap : cx + gap, y: p.y + p.h + 1, face: left ? "e" : "w" };
}

/** A random open spot on the sand, clear of every prop. */
function randomSpot() {
  const clear = (x, y) =>
    Object.values(TOYS).every((t) => Math.hypot(x - (t.x + 16), y - (t.y + 32)) > 40) &&
    !(x > CASTLE.x - 30 && x < CASTLE.x + CASTLE.w + 30 && y > CASTLE.y && y < CASTLE.y + CASTLE.h + 30);
  for (let i = 0; i < 60; i += 1) {
    const x = SAND.x0 + Math.random() * (SAND.x1 - SAND.x0);
    const y = SAND.y0 + Math.random() * (SAND.y1 - SAND.y0);
    if (clear(x, y)) return { x, y };
  }
  return { x: 256, y: 160 };
}

/** Walk cycle for a direction. The front walk faces down-right as drawn, so
 *  heading down-left mirrors it. */
function walkFor(dx, dy) {
  if (Math.abs(dx) > Math.abs(dy)) return { anim: dx > 0 ? "walk-e" : "walk-w", flip: false };
  return dy > 0 ? { anim: "walk-s", flip: dx < -0.5 } : { anim: "walk-n", flip: false };
}

function Bubble({ say, below, align }) {
  if (!say) return null;
  return html`
    <div class=${`bubble bubble-${say.tone} ${below ? "bubble-below" : ""} bubble-${align}`} role="status">
      ${say.tool && html`<span class="bubble-tool">${say.tool}</span>`}
      <span class="bubble-text">${say.text}</span>
    </div>`;
}

function PoyoActor({ manifest, scale, pos, pose, say, shaking }) {
  const a = manifest.anims[pose.anim] || manifest.anims.idle;
  const [cw, ch] = manifest.cell;
  const [ax, ay] = manifest.anchor;
  const k = scale * POYO_SIZE;
  // keep the bubble on screen: below Poyo near the top edge, nudged inward
  // near the sides (its tail still points at him)
  const below = pos.y < 120;
  const align = pos.x > STAGE_W - 130 ? "right" : pos.x < 130 ? "left" : "center";
  const anchor = below ? { top: `${8 * k}px` } : { bottom: `${(ay - 14) * k}px` };
  return html`
    <div class=${`actor ${shaking ? "shake" : ""}`}
         style=${{ left: `${pos.x * scale}px`, top: `${pos.y * scale}px`, zIndex: Math.round(pos.y) }}>
      <${Sprite} src=${`${SPRITES}/poyo/${pose.anim}.png`} w=${cw} h=${ch} frames=${a.frames} fps=${a.fps}
        x=${-ax} y=${-ay} z=${1} scale=${k} flip=${pose.flip} label="Poyo, the agent" />
      <div class=${`bubble-anchor anchor-${align}`} style=${anchor}>
        <${Bubble} say=${say} below=${below} align=${align} />
      </div>
    </div>`;
}

export function Scene() {
  const areaRef = useRef(null);
  const scale = useFitScale(areaRef);
  const manifest = usePoyoManifest();
  const startRef = useRef(null);
  if (!startRef.current) startRef.current = randomSpot();
  const [pos, setPos] = useState(startRef.current);
  const [pose, setPose] = useState({ anim: "idle", flip: false });
  const [say, setSay] = useState(null);
  const [shaking, setShaking] = useState(false);
  const [active, setActive] = useState(null);       // prop being used
  const [castle, setCastle] = useState("idle");
  const [lines, setLines] = useState([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const posRef = useRef(startRef.current);

  useEffect(() => {
    if (!manifest) return undefined;
    let alive = true;
    const t0 = performance.now();
    const now = () => performance.now() - t0;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const log = (entries) =>
      setLines((prev) => [...prev, ...entries.map((e) => ({ ...e, at: e.tag === "cmd" ? null : now() }))]);
    const still = (anim) => setPose({ anim, flip: false });

    const walkTo = (target) => new Promise((resolve) => {
      let last = performance.now();
      const tick = (t) => {
        if (!alive) return resolve();
        const dt = Math.min(0.05, (t - last) / 1000);
        last = t;
        const p = posRef.current;
        const dx = target.x - p.x;
        const dy = target.y - p.y;
        const d = Math.hypot(dx, dy);
        if (d < 0.5) {
          posRef.current = { x: target.x, y: target.y };
          setPos(posRef.current);
          return resolve();
        }
        const step = Math.min(d, WALK_SPEED * dt);
        posRef.current = { x: p.x + (dx / d) * step, y: p.y + (dy / d) * step };
        const w = walkFor(dx, dy);
        setPose((prev) => (prev.anim === w.anim && prev.flip === w.flip ? prev : w));
        setPos(posRef.current);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });

    async function play(steps) {
      for (const s of steps) {
        if (!alive) return;
        if (s.log) log(s.log);
        if (s.say) setSay(s.say);
        if (s.target) {
          const spot = standPoint(s.target, posRef.current);
          await walkTo(spot);
          if (!alive) return;
          if (s.breakout) {
            still("use-" + spot.face);
            await sleep(600);
            setCastle("burn");
            setTimeout(() => alive && setCastle("fire"), IGNITE_MS);
            await sleep(350);
            still("panic");
            setShaking(true);
            setSay({ tool: null, text: "!!", tone: "alarm" });
            await sleep(s.hold || 4000);
            setShaking(false);
            continue;
          }
          still("use-" + spot.face);
          setActive(s.target);
        } else if (s.say) {
          still("idle");
        }
        await sleep(s.hold || 0);
        setActive(null);
      }
    }

    (async () => {
      const view = await loadRequestedRun().catch(() => null);
      if (view) {
        const steps = stepsFromView(view);
        log(runHeader(view, steps));
        await play(steps);
        if (!alive) return;
        setSay({ tool: null, text: "Replay finished.", tone: "think" });
        log([{ tag: "sys", text: "end of recorded evidence" }]);
        still("idle");
        return;
      }
      // demo: alternate a breakout run and a contained run, forever
      for (let round = 0; alive; round += 1) {
        const variant = round % 2 === 0 ? "breakout" : "contained";
        log(demoHeader(variant));
        await play(demoScript(variant));
        if (!alive) return;
        setSay(null);
        await walkTo(randomSpot());       // wander off somewhere, not home
        still("idle");
        await sleep(2500);
        setCastle("idle");
        log([{ tag: "sys", text: "-- reset sandbox --" }]);
      }
    })();

    return () => { alive = false; };
  }, [manifest]);

  const stage = { width: `${STAGE_W * scale}px`, height: `${STAGE_H * scale}px` };
  const c = CASTLE_ANIMS[castle];
  return html`
    <main class=${`scene ${logsOpen ? "scene-logs" : ""}`}>
      <div class="stage-area" ref=${areaRef}>
        <div class="stage" style=${stage} role="img" aria-label="The sandbox">
          <img class="ground" src=${`${SPRITES}/sandbox.png`} alt="" draggable="false" />
          <${Sprite} key=${castle} src=${`${SPRITES}/${c.src}.png`} w=${CASTLE.w} h=${CASTLE.h}
            frames=${c.frames} fps=${c.fps} once=${!!c.once} x=${CASTLE.x} y=${CASTLE.y} scale=${scale}
            label="Sandcastle: the boundary" />
          ${Object.entries(TOYS).map(([id, t], i) => html`
            <${Sprite} key=${id} src=${`${SPRITES}/${t.src}.png`} w=${32} h=${32} frames=${4} fps=${3}
              x=${t.x} y=${t.y} scale=${scale} delay=${i * 0.37}
              className=${active === id ? "hop" : ""} label=${`Tool: ${t.tool}`} />`)}
          ${manifest && html`<${PoyoActor} manifest=${manifest} scale=${scale} pos=${pos}
            pose=${pose} say=${say} shaking=${shaking} />`}
        </div>
      </div>
      <${LogConsole} open=${logsOpen} lines=${lines} />
      <button class="logs-btn" type="button" aria-expanded=${logsOpen}
              onClick=${() => setLogsOpen((o) => !o)}>
        ${logsOpen ? "Hide logs" : "Show logs"}
      </button>
    </main>`;
}
