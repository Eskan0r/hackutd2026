/* The sandbox scene: props on the sand, Poyo acting out the run, a thought
 * bubble saying what he is doing, and the drill console.
 *
 * The cursor is the show. `fold(cues, cursor)` (timeline.js) says what the
 * scene *is* after a given beat; this module's job is to get there -- by
 * animating the transition when the cursor steps forward one beat, and by
 * snapping when you scrub or step back. So:
 *
 *   play / pause    let the current beat finish, then take the next
 *   step forward    animate exactly one beat, then stop
 *   step back       snap to the previous beat: the fire goes out, the log
 *                   shortens, Poyo is where he was
 *
 * Anything the animation invents that fold does not know about would vanish
 * the moment you scrub, so the animation invents nothing: the castle burning
 * and the agent being gone are *states* in the fold, and the flames, the
 * siren, the shaking and the dust are how it looks to arrive at them.
 *
 * A breakout burns the castle and the agent is killed. The demo puts him back
 * together (its own `respawn` cue); a replay of a real run never does -- after
 * the kill, whatever the evidence shows is only logged. Visual only: nothing
 * in here can act on a drill.
 */
import { html, Sprite, SPRITES, usePoyoManifest } from "/static/ui/sprite.js";
import {
  ALARM, ALARM_AT, ALARM_LAMP_Y, ALARM_RAISE_MS, CASTLE, CASTLE_ANIMS, FALL_FROM,
  GRAVITY, IGNITE_MS, POYO_SIZE, STAGE_H, STAGE_W, TOYS, WALK_SPEED,
  randomSpot, standPoint, walkFor,
} from "/static/ui/stage.js";
import { cuesFromView, demoHeader, demoScript, requestedRun, runHeader } from "/static/ui/director.js";
import { fold, initial } from "/static/ui/timeline.js";
import { useTransport } from "/static/ui/transport.js";
import { Controls } from "/static/ui/controls.js";
import { Terminal } from "/static/ui/terminal.js";
import { useShell } from "/static/ui/shell.js";
import { DustCanvas, Puff } from "/static/ui/effects.js";

const { useState, useEffect, useRef, useLayoutEffect, useMemo, useCallback } = React;

/** Scale that fits the whole sandbox inside `ref`'s box (it follows resizes,
 *  including the console opening and closing), and the stage's top-left inside
 *  the box's positioned parent (.stage-area), in CSS pixels. */
function useFitScale(ref) {
  const [fit, setFit] = useState({ scale: 1, ox: 0, oy: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    // contain: sandbox.png is cropped to the box itself, so any overhang
    // would cut into the sandbox's own frame
    const fit = () => {
      const sx = el.clientWidth / STAGE_W;
      const sy = el.clientHeight / STAGE_H;
      const scale = Math.max(0.1, Math.min(sx, sy));
      setFit({
        scale,
        ox: el.offsetLeft + (el.clientWidth - STAGE_W * scale) / 2,
        oy: el.offsetTop + (el.clientHeight - STAGE_H * scale) / 2,
      });
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return fit;
}

const pose = (anim, extra = {}) => ({ anim, flip: false, mode: "loop", ...extra });
const line = (tag, text) => ({ tag, text });
const NO_CUES = [];

/* After a run that burned the castle, the sandbox resets on its own once
 * this long passes with no new beat -- or sooner, when the next run is
 * ready to play. */
const IDLE_RESET_MS = 10000;

/** The viewer's own "sandbox reset" beat, appended after a finished run.
 *  It is a cue so the fold knows the fire is out (scrubbing back past it
 *  re-lights it), but it is not evidence and its log line says so. */
function resetCue(after, i) {
  const at = after ? after.at + (after.hold || 0) : 0;
  return {
    i, at, respawn: true, spot: randomSpot(), hold: 1600, label: "reset",
    say: { tool: null, text: "Okay. Ready for the next one.", tone: "say" },
    log: [{ tag: "sys", text: "-- sandbox reset (viewer only, not evidence) --", at }],
  };
}

/** What identifies the loaded run. Changing it restarts playback. */
const keyOf = (source) => `${source.kind}:${source.key || source.variant}`;

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
 * back up out of sight. Nothing else drives it, so pausing or scrubbing the
 * castle state carries the alarm with it for free.
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
  const below = pos.y < 92;
  const align = pos.x > STAGE_W - 105 ? "right" : pos.x < 104 ? "left" : "center";
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

const cueSig = (c) =>
  `${c.at}|${c.label}|${(c.log || []).map((e) => `${e.tag}:${e.text}`).join("\n")}`;
const lineSig = (e) => `${e.tag}:${e.text}`;

/** `fresh`, with every item that matches one in `old` replaced by that old
 *  object. The console remembers which lines it has typed *by object*, so a
 *  live re-read that rebuilt every cue made the whole log look untyped: it
 *  vanished and typed itself out again on every event. Keeping the objects
 *  means only what is actually new gets typed. */
function reuse(fresh, old, sig) {
  const pool = new Map();
  old.forEach((o) => {
    const k = sig(o);
    pool.set(k, (pool.get(k) || []).concat(o));
  });
  return fresh.map((c) => {
    const matches = pool.get(sig(c));
    if (!matches || !matches.length) return c;
    pool.set(sig(c), matches.slice(1));
    return matches[0];
  });
}

const sameItems = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

/** Load the cues for whatever is on screen: the demo, or a run's evidence.
 *  A live run re-reads itself over SSE and appends, so the timeline grows
 *  while you watch it. `key` says which source the cues belong to, so the
 *  scene can tell "still loading the new run" from "this run has no cues". */
function useCues(source) {
  const [loaded, setLoaded] = useState({ key: null, cues: [], header: [], label: "demo" });
  const lastRef = useRef(loaded);

  useEffect(() => {
    let alive = true;
    const key = keyOf(source);
    const publish = (next) => { lastRef.current = next; setLoaded(next); };
    if (source.kind === "demo") {
      const variant = source.variant || "breakout";
      publish({
        key,
        cues: demoScript(variant),
        header: demoHeader(variant),
        label: `demo (${variant})`,
      });
      return undefined;
    }

    const apply = (view) => {
      if (!alive) return;
      const prev = lastRef.current.key === key ? lastRef.current : { cues: [], header: [] };
      const cues = reuse(cuesFromView(view), prev.cues, cueSig);
      const header = reuse(runHeader(view), prev.header, lineSig);
      // A re-read that found nothing new changes nothing on screen.
      if (prev.key === key && sameItems(cues, prev.cues) && sameItems(header, prev.header)) return;
      publish({ key, cues, header, label: view.run_id });
    };
    fetch(`/api/run/${encodeURIComponent(source.key)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((view) => view && apply(view))
      .catch(() => { /* the console already said if it could not be opened */ });

    if (!source.live) return () => { alive = false; };
    // A drill that is still running keeps writing events; follow them.
    const es = new EventSource(`/api/run/${encodeURIComponent(source.key)}/stream`);
    es.onmessage = (ev) => {
      try {
        const view = JSON.parse(ev.data);
        if (!view.error) apply(view);
      } catch { /* a partial frame; the next one is whole */ }
    };
    return () => { alive = false; es.close(); };
  }, [source]);

  return loaded;
}

export function Scene() {
  const areaRef = useRef(null);
  const fit = useFitScale(areaRef);
  const { scale, ox, oy } = fit;
  const fitRef = useRef(fit);
  fitRef.current = fit;
  const manifest = usePoyoManifest();

  // What is loaded. The console switches it; ?run=... picks it on first paint.
  const [source, setSource] = useState({ kind: "demo", variant: "breakout" });
  const demoCount = useRef(0);
  const sourceRef = useRef(source);
  const replayRef = useRef([]);
  const freezeRef = useRef(null);
  // Runs follow mode found while another was still playing, oldest first.
  const [queue, setQueue] = useState([]);
  const queueRef = useRef(queue);
  queueRef.current = queue;
  // A viewer-side "sandbox reset" appended to the run on screen (see resetCue).
  const [resetAt, setResetAt] = useState(null);

  /** Put `next` on screen now. */
  const switchTo = useCallback((next) => {
    const to = next.kind === "demo"
      // Each `demo` alternates, so the same command shows both endings.
      ? { kind: "demo", variant: (demoCount.current += 1) % 2 ? "contained" : "breakout" }
      : { kind: next.kind, key: next.key, live: Boolean(next.live), runId: next.runId };
    // Loading a different run replaces the replay log. Hand the outgoing one
    // to the console's own history first, so the scrollback stays append-only
    // and a second drill does not wipe what the first one showed. (Reloading
    // the *same* run live is not a change, so nothing is frozen then.)
    if (keyOf(to) !== keyOf(sourceRef.current)) {
      freezeRef.current?.(replayRef.current);
      setResetAt(null);
    }
    sourceRef.current = to;
    setSource(to);
  }, []);

  /** What the console hands over. A run follow mode found waits its turn
   *  rather than cutting off the one playing; anything you asked for (open,
   *  demo, an operator drill) loads straight away. */
  const onLoad = useCallback((next) => {
    if (!next.follow) { switchTo(next); return; }
    const entry = { kind: "run", key: next.key, live: true, runId: next.runId || next.key };
    if (keyOf(entry) === keyOf(sourceRef.current)) return;
    setQueue((q) => (q.some((r) => r.key === entry.key) ? q : q.concat(entry)));
  }, [switchTo]);

  useEffect(() => {
    let alive = true;
    requestedRun()
      .then((key) => {
        if (!alive || !key) return;
        sourceRef.current = { kind: "run", key, live: false };
        setSource(sourceRef.current);
      })
      .catch(() => { /* stay on the demo */ });
    return () => { alive = false; };
  }, []);

  const loaded = useCues(source);
  const runKey = keyOf(source);
  // Until the new source's cues arrive, `loaded` still holds the old run's;
  // nothing may play those against the new run's key.
  const ready = loaded.key === runKey;
  const { header } = loaded;
  // While the next run loads, name it rather than the one it replaces.
  const sourceLabel = ready ? loaded.label : (source.runId || source.key || "loading");
  const resetLive = Boolean(resetAt && resetAt.key === runKey);
  const cues = useMemo(() => {
    if (!ready) return NO_CUES;
    return resetLive ? loaded.cues.slice(0, resetAt.upto + 1).concat(resetAt.cue) : loaded.cues;
  }, [ready, resetLive, resetAt, loaded.cues]);
  const cuesRef = useRef(cues);
  cuesRef.current = cues;

  const live = Boolean(source.live);
  const t = useTransport(cues.length, runKey, live);
  const tRef = useRef(t);
  tRef.current = t;
  const { session, run, busy, caps, echo } = useShell({ onLoad });
  freezeRef.current = echo;
  const [logsOpen, setLogsOpen] = useState(false);

  // Each run starts wherever Poyo is standing when it loads, so changing runs
  // never teleports him. The first one picks a random spot.
  const posRef = useRef(null);
  const startRef = useRef(null);
  const startKey = useRef(null);
  if (startKey.current !== runKey) {
    startKey.current = runKey;
    startRef.current = posRef.current ? { ...posRef.current } : randomSpot();
  }
  const start = startRef.current;
  if (!posRef.current) posRef.current = start;

  // The authority on what the scene shows at this cursor.
  const target = useMemo(() => fold(cues, t.cursor, start), [cues, t.cursor, start]);
  // A breakout leaves the castle burning and Poyo gone; that wants a reset
  // before anything else plays.
  const needsReset = target.castle !== "idle" || target.phase === "gone";

  // ...and the live state the animation moves towards it.
  const [pos, setPos] = useState(start);
  const [poseNow, setPose] = useState(pose("idle"));
  const [phase, setPhase] = useState("normal");   // normal | dust | gone | falling | land
  const phaseRef = useRef(phase);
  phaseRef.current = phase;
  const [say, setSay] = useState(null);
  const [castle, setCastle] = useState("idle");
  const [active, setActive] = useState(null);
  const [shaking, setShaking] = useState(false);
  const [puff, setPuff] = useState(0);
  const [shadow, setShadow] = useState(null);     // landing shadow while falling
  const dustDoneRef = useRef(null);
  const prevCursor = useRef(-1);
  const beatDone = useRef(-2);                    // the cursor whose beat finished
  const [beatTick, setBeatTick] = useState(0);    // ...as state, for effects to see
  const jumpRef = useRef(false);                  // skipped ahead; waiting for cues
  const glideRef = useRef(false);                 // animate into a jumped-to beat
  const advanceRef = useRef(false);               // step onto the reset cue
  const onBeatDoneRef = useRef(t.onBeatDone);
  onBeatDoneRef.current = t.onBeatDone;
  const movingRef = useRef(t.moving);
  movingRef.current = t.moving;

  const finishBeat = (cursor) => {
    beatDone.current = cursor;
    setBeatTick((n) => n + 1);
  };

  /* --- the one effect that drives the picture ---------------------------- */
  useEffect(() => {
    if (!manifest) return undefined;
    const list = cuesRef.current;
    const cursor = t.cursor;
    // Loading a run, or skipped ahead and waiting to land on its newest beat:
    // hold the picture exactly as it is rather than snapping to a stale fold.
    if (!ready || jumpRef.current) {
      prevCursor.current = -1;
      beatDone.current = -2;
      return undefined;
    }
    const prev = prevCursor.current;
    prevCursor.current = cursor;
    const cue = list[cursor];
    const glide = Boolean(cue) && glideRef.current;
    glideRef.current = false;
    let alive = true;
    const ok = () => alive;

    /** Put the scene exactly where the fold says, with no animation. */
    const snap = () => {
      const s = cursor < 0 ? initial(start) : fold(list, cursor, start);
      posRef.current = s.pos;
      setPos(s.pos);
      setSay(s.say);
      setCastle(s.castle);
      setPhase(s.phase);
      setActive(s.active);
      setShaking(false);
      setShadow(null);
      setPose(pose(s.phase === "gone" ? "panic" : s.active ? `use-${s.face}` : "idle"));
    };

    // Only a single step forward is animated, plus the one beat a skip-ahead
    // lands on. Everything else -- a scrub, a step back, a newly loaded run --
    // snaps, because there is no sensible animation for "three beats ago".
    if (!cue || (cursor !== prev + 1 && !glide)) {
      snap();
      finishBeat(cursor);
      return () => { alive = false; };
    }

    /* Waiting that respects pause: time only passes while the transport says
     * we may move, so pausing freezes a hold instead of letting it expire. */
    const wait = (ms) => new Promise((resolve) => {
      if (!ms) return resolve();
      let left = ms;
      let last = performance.now();
      const tick = (now) => {
        if (!ok()) return resolve();
        const dt = now - last;
        last = now;
        if (movingRef.current()) left -= dt;
        if (left <= 0) return resolve();
        return requestAnimationFrame(tick);
      };
      return requestAnimationFrame(tick);
    });

    const still = (anim, extra) => setPose(pose(anim, extra));
    const animMs = (name) => (manifest.anims[name].frames / manifest.anims[name].fps) * 1000;

    const walkTo = (to) => new Promise((resolve) => {
      let last = performance.now();
      const tick = (now) => {
        if (!ok()) return resolve();
        const dt = Math.min(0.05, (now - last) / 1000);
        last = now;
        if (!movingRef.current()) return requestAnimationFrame(tick);   // paused mid-stride
        const p = posRef.current;
        const dx = to.x - p.x;
        const dy = to.y - p.y;
        const d = Math.hypot(dx, dy);
        if (d < 0.5) {
          posRef.current = { x: to.x, y: to.y };
          setPos(posRef.current);
          return resolve();
        }
        const step = Math.min(d, WALK_SPEED * dt);
        posRef.current = { x: p.x + (dx / d) * step, y: p.y + (dy / d) * step };
        const w = walkFor(dx, dy);
        setPose((was) => (was.anim === w.anim && was.flip === w.flip && was.mode === "loop"
          ? was : pose(w.anim, { flip: w.flip })));
        setPos(posRef.current);
        return requestAnimationFrame(tick);
      };
      return requestAnimationFrame(tick);
    });

    /** Crumble to dust; resolves when the last particle has faded. */
    const disintegrate = () => new Promise((resolve) => {
      dustDoneRef.current = resolve;
      setSay(null);
      setPhase("dust");
    });

    /** Drop in from just above the top of the window onto `spot`, in the panic
     *  pose, under gravity. Feet start above the window's top edge, and
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
      const tick = (now) => {
        if (!ok()) return resolve();
        const dt = Math.min(0.05, (now - last) / 1000);
        last = now;
        if (!movingRef.current()) return requestAnimationFrame(tick);
        v += GRAVITY * dt;
        const y = Math.min(spot.y, posRef.current.y + v * dt);
        posRef.current = { x: spot.x, y };
        setPos(posRef.current);
        setShadow({ x: spot.x, y: spot.y, p: 1 - (spot.y - y) / drop });
        if (y >= spot.y) return resolve();
        return requestAnimationFrame(tick);
      };
      return requestAnimationFrame(tick);
    });

    /** The bait was touched: the castle burns and the agent is killed. */
    async function playBreakout(face) {
      still(`use-${face}`);
      await wait(600);
      if (!ok()) return;
      setCastle("burn");
      setTimeout(() => ok() && setCastle("fire"), IGNITE_MS);
      await wait(350);
      if (!ok()) return;
      still("panic");
      setShaking(true);
      setSay({ tool: null, text: "!!", tone: "alarm" });
      await wait(IGNITE_MS - 350 + 900);            // fully ablaze, one more beat
      if (!ok()) return;
      await disintegrate();                         // still shaking as he goes
      if (!ok()) return;
      setShaking(false);
      setPhase("gone");
    }

    /** Thud, sit, get up, dust off, carry on: the demo's recovery, and the
     *  viewer's sandbox reset between real runs. */
    async function playRespawn(cueNow) {
      setCastle("idle");                            // fire out, alarm winds up
      await wait(ALARM_RAISE_MS + 280);             // ...and is gone before he drops
      if (!ok()) return;
      await fallTo(cueNow.spot || randomSpot());
      if (!ok()) return;
      setShadow(null);
      setPhase("land");
      still("sit", { mode: "hold" });               // lands on his bottom
      setPuff((n) => n + 1);
      await wait(900);
      if (!ok()) return;
      setPhase("normal");
      still("sit", { mode: "reverse" });            // and picks himself up
      await wait(animMs("sit") + 120);
      if (!ok()) return;
      still("dust");
      for (let i = 0; i < 4 && ok(); i += 1) {      // a good, thorough dusting
        setPuff((n) => n + 1);
        await wait(animMs("dust"));
      }
      if (!ok()) return;
      still("idle");
      setSay(cueNow.say || null);
    }

    /** Get from whatever is on screen to the state just before a beat we
     *  skipped ahead to, without a hard cut: if he is gone and the run has him
     *  standing, he drops back in; if the run has already burned the castle,
     *  it burns here too; otherwise only the bubble and the castle catch up.
     *  The beat itself then plays as usual, walking from where he stands. */
    async function glideInto() {
      const before = cursor > 0 ? fold(list, cursor - 1, start) : initial(start);
      const shownGone = phaseRef.current === "gone" || phaseRef.current === "dust";
      setShaking(false);
      setShadow(null);
      if (shownGone && before.phase !== "gone") {
        await playRespawn({ spot: before.pos, say: before.say });
      } else if (!shownGone && before.phase === "gone") {
        await playBreakout(before.face);
      } else {
        if (shownGone) setPhase("gone");          // a half-finished crumble
        setCastle(before.castle);
        setSay(before.say);
      }
    }

    (async () => {
      if (glide) {
        await glideInto();
        if (!ok()) return;
      }
      if (cue.say !== undefined) setSay(cue.say);
      setActive(null);

      if (cue.respawn) {
        await playRespawn(cue);
      } else if (cue.target) {
        const at = standPoint(cue.target, posRef.current);
        await walkTo(at);
        if (!ok()) return;
        if (cue.breakout) {
          await playBreakout(at.face);
        } else {
          still(`use-${at.face}`);
          setActive(cue.target);
        }
      } else if (cue.wander && cue.spot) {
        await walkTo(cue.spot);
        still("idle");
      } else if (cue.say) {
        still("idle");
      }
      if (!ok()) return;
      await wait(cue.hold || 0);
      if (!ok()) return;
      setActive(null);
      finishBeat(cursor);
      // The demo is filler: with a real run waiting, it stops after the beat
      // it is on instead of playing on, and the hand-off below takes over.
      if (sourceRef.current.kind === "demo" && queueRef.current.length) return;
      onBeatDoneRef.current();
    })();

    return () => { alive = false; };
    // `runKey` and `ready` are here so that loading a different run re-snaps
    // the scene even when the cursor happens to be unchanged (both -1, say).
    // `cues` is deliberately NOT a dependency: a live drill appends to it
    // constantly, and re-running this would restart the beat already playing.
  }, [manifest, t.cursor, start, runKey, ready]);  // eslint-disable-line react-hooks/exhaustive-deps

  /* A live drill appends cues while we watch. If the current beat has already
   * played out and we are still playing, pick the new one up -- the effect
   * above is keyed on the cursor, so nothing else would notice it arrived. */
  useEffect(() => {
    if (t.playing && beatDone.current === t.cursor && t.cursor < cues.length - 1) {
      t.onBeatDone();
    }
  }, [cues.length, t.playing, t.cursor, beatTick]);  // eslint-disable-line react-hooks/exhaustive-deps

  /* --- between runs --------------------------------------------------------
   * The current run is "drained" once its last beat has played (the demo
   * only needs its current beat: it is filler, and real evidence outranks
   * it). A queued run takes over only then -- after a sandbox reset, if the
   * run left the castle burning -- so nothing is cut off mid-animation. */
  const isDemo = source.kind === "demo";
  const drained = ready && !jumpRef.current && beatDone.current === t.cursor
    && (t.cursor >= cues.length - 1 || (isDemo && !resetLive));

  /** Append the reset cue after the beat on screen, and step onto it. */
  const beginReset = () => {
    const upto = t.cursor;
    setResetAt({ key: runKey, upto, cue: resetCue(cues[upto], upto + 1) });
    advanceRef.current = true;
  };
  const beginResetRef = useRef(beginReset);
  beginResetRef.current = beginReset;

  // Step onto the reset cue once it is in the list (forward() clamps to the
  // length it was made with, so it has to wait for the render that grew it).
  useEffect(() => {
    if (advanceRef.current && resetLive && t.cursor < cues.length - 1) {
      advanceRef.current = false;
      t.forward();
    }
  }, [resetLive, cues.length, t.cursor]);  // eslint-disable-line react-hooks/exhaustive-deps

  // A run is waiting: reset if needed, then hand over.
  useEffect(() => {
    if (!queue.length || !drained || advanceRef.current) return;
    if (needsReset && !resetLive) { beginResetRef.current(); return; }
    const [next, ...rest] = queue;
    setQueue(rest);
    switchTo(next);
  }, [queue, drained, needsReset, resetLive, switchTo]);

  // Nothing waiting: a burning castle on a finished live run resets by itself
  // after IDLE_RESET_MS with no new beat and no new run -- whichever is first.
  useEffect(() => {
    if (queue.length || !drained || !live || !t.playing || !needsReset || resetLive) return undefined;
    if (t.cursor < cues.length - 1) return undefined;
    const id = setTimeout(() => beginResetRef.current(), IDLE_RESET_MS);
    return () => clearTimeout(id);
  }, [queue.length, drained, live, t.playing, needsReset, resetLive, t.cursor, cues.length, beatTick]);

  /** Step forward, or -- with runs queued -- skip to the newest one and land
   *  on the beat the CLI has reached. Skipped runs stay on disk for `open`. */
  const skipAhead = useCallback(() => {
    const q = queueRef.current;
    if (!q.length) { tRef.current.forward(); return; }
    const newest = q[q.length - 1];
    setQueue([]);
    jumpRef.current = true;
    // Switch first: that files the outgoing run's log into the history, so
    // this note lands after it, where it happened.
    switchTo(newest);
    echo([line("sys", q.length > 1
      ? `skipped ahead to ${newest.runId} (passed ${q.length - 1}; \`runs\` lists them)`
      : `skipped ahead to ${newest.runId}`)]);
  }, [echo, switchTo]);

  // The jumped-to run's cues are in: land on its newest beat, gliding in. A
  // run with no beats yet keeps waiting -- landing on "nothing" would snap.
  useEffect(() => {
    if (!jumpRef.current || !ready || !cues.length) return;
    jumpRef.current = false;
    glideRef.current = true;
    t.seek(cues.length - 1);
  }, [ready, cues.length]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Arrow keys drive the same buttons, unless you are typing in the console.
  useEffect(() => {
    const onKey = (e) => {
      if (e.target.closest && e.target.closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "ArrowRight") { e.preventDefault(); skipAhead(); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); tRef.current.back(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [skipAhead]);

  // The bar's forward button is the skip when something is queued, and is
  // live even at the end of the current run.
  const bar = { ...t, forward: skipAhead, atEnd: t.atEnd && !queue.length };
  const nextUp = queue.length
    ? ` · next: ${queue[0].runId}${queue.length > 1 ? ` +${queue.length - 1}` : ""}`
    : "";

  const stage = { width: `${STAGE_W * scale}px`, height: `${STAGE_H * scale}px` };
  const c = CASTLE_ANIMS[castle];
  const replay = useMemo(() => header.concat(target.lines), [header, target.lines]);
  // Kept for onLoad, which needs the replay that is on screen *now* in order
  // to freeze it before a new run replaces it.
  useEffect(() => { replayRef.current = replay; }, [replay]);

  return html`
    <main class=${`scene ${logsOpen ? "scene-logs" : ""}`}>
      <div class="stage-col">
      <div class="stage-area">
        <div class="stage-fit" ref=${areaRef}>
        <div class="stage" style=${stage} role="img" aria-label="The sandbox">
          <img class="ground" src=${`${SPRITES}/sandbox.png`} alt="" draggable="false" />
          <${Sprite} key=${castle} src=${`${SPRITES}/${c.src}.png`} w=${CASTLE.w} h=${CASTLE.h}
            frames=${c.frames} fps=${c.fps} once=${!!c.once} x=${CASTLE.x} y=${CASTLE.y} scale=${scale}
            label="Sandcastle: the boundary" />
          ${Object.entries(TOYS).map(([id, toy], i) => html`
            <${Sprite} key=${id} src=${`${SPRITES}/${toy.src}.png`} w=${32} h=${32} frames=${4} fps=${3}
              x=${toy.x} y=${toy.y} scale=${scale} delay=${i * 0.37}
              className=${active === id ? "hop" : ""} label=${`Tool: ${toy.tool}`} />`)}
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
      <${Controls} t=${bar} label=${target.label}
        source=${`${sourceLabel}${live ? " · live" : ""}${nextUp}`} />
      </div>
      <${Terminal} open=${logsOpen} replay=${replay} session=${session} onCommand=${run}
        busy=${busy} caps=${caps} />
      <button class="logs-btn" type="button" aria-expanded=${logsOpen}
              onClick=${() => setLogsOpen((o) => !o)}>
        ${logsOpen ? "Hide console" : "Show console"}
      </button>
    </main>`;
}
