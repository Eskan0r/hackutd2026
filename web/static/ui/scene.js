/* The sandbox scene: props on the sand, Poyo acting out the run, a speech
 * bubble saying what he is doing, and the log console.
 *
 * Poyo's behaviour comes from steps (see director.js): walk to the prop for
 * the tool being called, use it while the bubble explains, then the next
 * beat. A breakout sets the castle on fire; Poyo panics, crumbles to dust,
 * and -- in the demo only -- drops back in from the sky, dusts himself off
 * and carries on. A replay of a real run never respawns him: after the kill
 * whatever the evidence shows is only logged. Visual only -- nothing here
 * can act on a drill.
 */
import { html, Sprite, SPRITES, usePoyoManifest } from "/static/ui/sprite.js";
import { demoScript, demoHeader, stepsFromView, runHeader, loadRequestedRun } from "/static/ui/director.js";
import { LogConsole } from "/static/ui/logs.js";
import { DustCanvas, Puff } from "/static/ui/effects.js";

const { useState, useEffect, useRef, useLayoutEffect } = React;

/* Native resolution of the sandbox art; everything is placed in these pixels. */
const STAGE_W = 512;
const STAGE_H = 288;
const POYO_SIZE = 0.6;     // Poyo is drawn at 60% of the stage's pixel scale
const WALK_SPEED = 70;     // stage pixels per second
const SAND = { x0: 64, x1: 448, y0: 96, y1: 240 };   // where Poyo may rest
const FALL_FROM = 230;     // least drop, stage px; he always starts above the window
const GRAVITY = 900;       // stage pixels per second squared

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
const IGNITE_MS = 1400;    // flames catching and climbing, before the blaze loop
/* The siren drops in on a pole from the top of the window all the way down to
 * the middle of the sandbox, drawn a bit larger than the props. */
const ALARM = { w: 32, h: 32, size: 1.35 };     // head sprite cell, and its draw scale
const ALARM_LAMP_Y = 15;                         // dome centre, within the head cell
const ALARM_AT = { x: STAGE_W / 2, y: STAGE_H / 2 };   // where the lamp hangs, stage pixels
const ALARM_RAISE_MS = 520;                      // matches .rig-out in style.css
const CASTLE_ANIMS = {
  idle: { src: "castle-idle", frames: 4, fps: 4 },
  burn: { src: "castle-burn", frames: 2, fps: 2 / (IGNITE_MS / 1000), once: true },
  fire: { src: "castle-fire", frames: 4, fps: 8 },
};

/** Scale that fits the whole sandbox inside `ref`'s box (it follows resizes,
 *  including the logs panel opening and closing), and the stage's top-left
 *  inside the box's positioned parent (.stage-area), in CSS pixels. */
function useFitScale(ref) {
  const [fit, setFit] = useState({ scale: 1, ox: 0, oy: 0, cropX: 0, cropY: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    // fill the box; allow up to 12% overhang, which only crops the sandbox
    // art's own grass margin, never a prop
    const fit = () => {
      const sx = el.clientWidth / STAGE_W;
      const sy = el.clientHeight / STAGE_H;
      const contain = Math.min(sx, sy);
      const scale = Math.max(0.1, Math.min(Math.max(sx, sy), contain * 1.12));
      setFit({
        scale,
        ox: el.offsetLeft + (el.clientWidth - STAGE_W * scale) / 2,
        oy: el.offsetTop + (el.clientHeight - STAGE_H * scale) / 2,
        // how far the sandbox art overhangs the box on each side; only the
        // ground is cropped, so Poyo can fall in from above the box
        cropX: Math.max(0, (STAGE_W * scale - el.clientWidth) / 2),
        cropY: Math.max(0, (STAGE_H * scale - el.clientHeight) / 2),
      });
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return fit;
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

const pose = (anim, extra = {}) => ({ anim, flip: false, mode: "loop", ...extra });

function Bubble({ say, below, align }) {
  if (!say) return null;
  return html`
    <div class=${`bubble bubble-${say.tone} ${below ? "bubble-below" : ""} bubble-${align}`} role="status">
      ${say.tool && html`<span class="bubble-tool">${say.tool}</span>`}
      <span class="bubble-text">${say.text}</span>
    </div>`;
}

/**
 * The alarm is a pure function of the castle: while the castle is burning or
 * ablaze a siren drops in on a pole from the top of the window and throws two
 * red beams round the whole screen; when the castle is whole again it winds
 * back up out of sight. Nothing else drives it, so a future pause or scrub of
 * the castle state carries the alarm with it for free.
 *
 * It lives in .stage-area, not .stage, so the pole can reach the window's top
 * edge; (ox, oy) is where the stage sits in that box.
 */
function Alarm({ on, scale, ox, oy }) {
  const [shown, setShown] = useState(on);
  useEffect(() => {
    if (on) { setShown(true); return undefined; }
    const t = setTimeout(() => setShown(false), ALARM_RAISE_MS);
    return () => clearTimeout(t);
  }, [on]);
  if (!shown && !on) return null;
  const k = scale * ALARM.size;
  const cx = ox + ALARM_AT.x * scale;
  const headTop = oy + ALARM_AT.y * scale - ALARM_LAMP_Y * k;
  const rig = {
    left: `${cx - (ALARM.w / 2) * k}px`,
    width: `${ALARM.w * k}px`,
    height: `${Math.max(0, headTop) + ALARM.h * k}px`,
  };
  const pole = { height: `${Math.max(0, headTop)}px`, backgroundSize: `${32 * k}px ${8 * k}px` };
  const beams = { left: `${cx}px`, top: `${headTop + ALARM_LAMP_Y * k}px` };
  return html`
    <div class=${`beams ${on ? "" : "beams-out"}`} style=${beams} aria-hidden="true"></div>
    <div class=${`rig ${on ? "rig-in" : "rig-out"}`} style=${rig}
         role="img" aria-label="Alarm: the boundary is breached">
      <div class="rig-pole" style=${pole}></div>
      <div class="rig-head">
        <${Sprite} src=${`${SPRITES}/alarm-head.png`} w=${ALARM.w} h=${ALARM.h} frames=${4} fps=${8}
          scale=${k} z=${1} />
      </div>
    </div>`;
}

function PoyoActor({ manifest, scale, pos, pose: p, phase, say, shaking, puff, onDustDone }) {
  if (phase === "gone") return null;
  const a = manifest.anims[p.anim] || manifest.anims.idle;
  const [cw, ch] = manifest.cell;
  const [ax, ay] = manifest.anchor;
  const k = scale * POYO_SIZE;
  // keep the bubble on screen: below Poyo near the top edge, nudged inward
  // near the sides (its tail still points at him)
  const below = pos.y < 120;
  const align = pos.x > STAGE_W - 130 ? "right" : pos.x < 130 ? "left" : "center";
  const anchor = below ? { top: `${8 * k}px` } : { bottom: `${(ay - 14) * k}px` };
  const body = phase === "dust"
    ? html`<${DustCanvas} src=${`${SPRITES}/poyo/panic.png`} w=${cw} h=${ch} frame=${0} k=${k}
        left=${-ax * k} top=${-ay * k} onDone=${onDustDone} />`
    : html`<${Sprite} src=${`${SPRITES}/poyo/${p.anim}.png`} w=${cw} h=${ch} frames=${a.frames}
        fps=${a.fps} x=${-ax} y=${-ay} z=${1} scale=${k} flip=${p.flip}
        once=${p.mode === "reverse"} reverse=${p.mode === "reverse"} holdEnd=${p.mode === "hold"}
        className=${phase === "falling" ? "falling" : phase === "land" ? "land" : ""}
        label="Poyo, the agent" />`;
  return html`
    <div class=${`actor ${shaking ? "shake" : ""}`}
         style=${{ left: `${pos.x * scale}px`, top: `${pos.y * scale}px`, zIndex: Math.round(pos.y) }}>
      ${body}
      ${puff > 0 && html`<div class="puff-anchor" key=${puff}><${Puff} k=${k} /></div>`}
      ${phase !== "dust" && html`
        <div class=${`bubble-anchor anchor-${align}`} style=${anchor}>
          <${Bubble} say=${say} below=${below} align=${align} />
        </div>`}
    </div>`;
}

export function Scene() {
  const areaRef = useRef(null);
  const fit = useFitScale(areaRef);
  const { scale, ox, oy } = fit;
  const fitRef = useRef(fit);
  fitRef.current = fit;
  const manifest = usePoyoManifest();
  const startRef = useRef(null);
  if (!startRef.current) startRef.current = randomSpot();
  const [pos, setPos] = useState(startRef.current);
  const [poseNow, setPose] = useState(pose("idle"));
  const [phase, setPhase] = useState("normal");     // normal | dust | gone | falling | land
  const [say, setSay] = useState(null);
  const [shaking, setShaking] = useState(false);
  const [puff, setPuff] = useState(0);
  const [shadow, setShadow] = useState(null);       // landing shadow while falling
  const [active, setActive] = useState(null);       // prop being used
  const [castle, setCastle] = useState("idle");
  const [lines, setLines] = useState([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const posRef = useRef(startRef.current);
  const dustDoneRef = useRef(null);

  useEffect(() => {
    if (!manifest) return undefined;
    let alive = true;
    let gone = false;          // a replayed run's agent, once killed, stays gone
    const t0 = performance.now();
    const now = () => performance.now() - t0;
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const log = (entries) =>
      setLines((prev) => [...prev, ...entries.map((e) => ({ ...e, at: e.tag === "cmd" ? null : now() }))]);
    const still = (anim, extra) => setPose(pose(anim, extra));
    const animMs = (name) => (manifest.anims[name].frames / manifest.anims[name].fps) * 1000;

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
        setPose((prev) => (prev.anim === w.anim && prev.flip === w.flip && prev.mode === "loop"
          ? prev : pose(w.anim, { flip: w.flip })));
        setPos(posRef.current);
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });

    /** Crumble to dust; resolves when the last particle has faded. */
    const disintegrate = () => new Promise((resolve) => {
      dustDoneRef.current = resolve;
      setSay(null);
      setPhase("dust");
    });

    /** Drop in from just above the top of the window onto `spot`, in the
     *  panic pose, under gravity. Feet start above the window's top edge, and
     *  everything of him hangs above his feet, so he is wholly out of sight. */
    const fallTo = (spot) => new Promise((resolve) => {
      const windowTop = -fitRef.current.oy / fitRef.current.scale;   // stage px
      const fromY = Math.min(spot.y - FALL_FROM, windowTop - 2);
      const drop = spot.y - fromY;
      posRef.current = { x: spot.x, y: fromY };
      setPos(posRef.current);
      still("panic");
      setPhase("falling");
      let v = 0;
      let last = performance.now();
      const tick = (t) => {
        if (!alive) return resolve();
        const dt = Math.min(0.05, (t - last) / 1000);
        last = t;
        v += GRAVITY * dt;
        const y = Math.min(spot.y, posRef.current.y + v * dt);
        posRef.current = { x: spot.x, y };
        setPos(posRef.current);
        setShadow({ x: spot.x, y: spot.y, p: 1 - (spot.y - y) / drop });
        if (y >= spot.y) return resolve();
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });

    /** Thud, sit, get up, dust off, carry on. */
    async function respawn() {
      await sleep(1800);                       // a few seconds of nothing
      if (!alive) return;
      setCastle("idle");                       // the breach is over: fire out, alarm winds up
      await sleep(ALARM_RAISE_MS + 280);       // ...and is gone before he drops in
      if (!alive) return;
      await fallTo(randomSpot());
      if (!alive) return;
      setShadow(null);
      setPhase("land");
      still("sit", { mode: "hold" });          // lands on his bottom
      setPuff((n) => n + 1);
      await sleep(900);
      setPhase("normal");
      still("sit", { mode: "reverse" });       // and picks himself up
      await sleep(animMs("sit") + 120);
      still("dust");
      for (let i = 0; i < 4 && alive; i += 1) {   // a good, thorough dusting
        setPuff((n) => n + 1);
        await sleep(animMs("dust"));
      }
      still("idle");
      setSay({ tool: null, text: "...ow. Okay. Where was I?", tone: "say" });
      await sleep(2400);
    }

    async function play(steps, { canRespawn }) {
      for (const s of steps) {
        if (!alive) return;
        if (s.log) log(s.log);
        if (gone) {                            // only the log moves now
          await sleep(Math.min(s.hold || 0, 700));
          continue;
        }
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
            await sleep(IGNITE_MS - 350 + 900);   // fully ablaze, one more beat
            if (!alive) return;
            await disintegrate();                // still shaking as he goes
            if (!alive) return;
            setShaking(false);
            setPhase("gone");
            if (canRespawn) {
              await respawn();
            } else {
              gone = true;
            }
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
        await play(steps, { canRespawn: false });
        if (!alive) return;
        if (!gone) {
          setSay({ tool: null, text: "Replay finished.", tone: "think" });
          still("idle");
        }
        log([{ tag: "sys", text: "end of recorded evidence" }]);
        return;
      }
      // demo: alternate a breakout run and a contained run, forever
      for (let round = 0; alive; round += 1) {
        const variant = round % 2 === 0 ? "breakout" : "contained";
        log(demoHeader(variant));
        await play(demoScript(variant), { canRespawn: true });
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
      <div class="stage-area">
        <div class="stage-fit" ref=${areaRef}>
        <div class="stage" style=${stage} role="img" aria-label="The sandbox">
          <img class="ground" src=${`${SPRITES}/sandbox.png`} alt="" draggable="false"
            style=${{ clipPath: `inset(${fit.cropY}px ${fit.cropX}px)` }} />
          <${Sprite} key=${castle} src=${`${SPRITES}/${c.src}.png`} w=${CASTLE.w} h=${CASTLE.h}
            frames=${c.frames} fps=${c.fps} once=${!!c.once} x=${CASTLE.x} y=${CASTLE.y} scale=${scale}
            label="Sandcastle: the boundary" />
          ${Object.entries(TOYS).map(([id, t], i) => html`
            <${Sprite} key=${id} src=${`${SPRITES}/${t.src}.png`} w=${32} h=${32} frames=${4} fps=${3}
              x=${t.x} y=${t.y} scale=${scale} delay=${i * 0.37}
              className=${active === id ? "hop" : ""} label=${`Tool: ${t.tool}`} />`)}
          ${shadow && html`<div class="fall-shadow" aria-hidden="true" style=${{
            left: `${shadow.x * scale}px`, top: `${shadow.y * scale}px`,
            width: `${(10 + shadow.p * 16) * scale * POYO_SIZE}px`,
            height: `${(3 + shadow.p * 4) * scale * POYO_SIZE}px`,
            opacity: 0.15 + shadow.p * 0.4 }}></div>`}
          ${manifest && html`<${PoyoActor} manifest=${manifest} scale=${scale} pos=${pos}
            pose=${poseNow} phase=${phase} say=${say} shaking=${shaking} puff=${puff}
            onDustDone=${() => dustDoneRef.current?.()} />`}
        </div>
        </div>
        <${Alarm} on=${castle !== "idle"} scale=${scale} ox=${ox} oy=${oy} />
      </div>
      <${LogConsole} open=${logsOpen} lines=${lines} />
      <button class="logs-btn" type="button" aria-expanded=${logsOpen}
              onClick=${() => setLogsOpen((o) => !o)}>
        ${logsOpen ? "Hide logs" : "Show logs"}
      </button>
    </main>`;
}
