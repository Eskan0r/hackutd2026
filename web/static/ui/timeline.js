/* The run as a seekable list of beats.
 *
 * The scene used to be an async loop: walk, await sleep, walk, await sleep.
 * That plays a run once and can never go back -- there is no "where we are",
 * only wherever the loop happens to have got to. So the loop is gone, and a
 * run is now a flat list of cues plus one pure function:
 *
 *     fold(cues, cursor, start) -> the whole scene, after cue `cursor`
 *
 * Every frame of the show is therefore reachable from the cursor alone, which
 * is what makes play, pause and step-back possible at all. fold is a *fold*
 * rather than a lookup because the state is path-dependent: which side of a
 * bucket Poyo stands on depends on where he walked from, so the beats have to
 * be replayed from the start. They are cheap and few, so replaying is free.
 *
 * The rule this file exists to keep: fold is the authority on what the scene
 * shows, and scene.js only animates its way towards it. Anything the animation
 * invents that fold does not know about disappears the moment you scrub, which
 * is exactly the bug a seekable timeline is supposed to make impossible.
 */
import { standPoint, toolOf } from "/static/ui/stage.js";

/** A resting scene: what you see before the first beat. */
export function initial(start) {
  return {
    pos: start,
    face: "e",
    active: null,       // prop being used right now
    say: null,          // thought bubble
    castle: "idle",     // idle | fire
    phase: "normal",    // normal | gone
    lines: [],          // log lines up to and including the cursor
    label: null,
    cue: null,
  };
}

/**
 * The scene after cue `cursor` (-1 = before the run started).
 *
 * Pure: same cues and cursor, same answer, every time. Stepping back is just
 * folding to a smaller cursor, which is why going back truly undoes things --
 * the castle is whole again, the log is shorter, Poyo is where he was.
 */
export function fold(cues, cursor, start) {
  const state = initial(start);
  for (let i = 0; i <= cursor && i < cues.length; i += 1) {
    const cue = cues[i];
    if (cue.log) state.lines = state.lines.concat(cue.log);
    // Only a cue that carries a bubble changes it. A log-only beat (a refused
    // retry after the kill, say) leaves the last thought up rather than
    // blanking it for a few hundred milliseconds -- and because that rule
    // lives here, scrubbing to the beat shows the same bubble that playing
    // through it does.
    if (cue.say !== undefined) state.say = cue.say || null;
    state.active = null;
    state.label = cue.label || null;
    state.cue = cue;

    // A respawn undoes a breakout: the fire is out and he is back on his feet.
    // The demo does this; a real run never does (see director.js).
    if (cue.respawn) {
      state.castle = "idle";
      state.phase = "normal";
      if (cue.spot) state.pos = cue.spot;
    }
    if (cue.wander && cue.spot) state.pos = cue.spot;

    if (cue.target) {
      const at = standPoint(cue.target, state.pos);
      state.pos = { x: at.x, y: at.y };
      state.face = at.face;
      if (cue.breakout) {
        // The bait was touched: the castle burns and the agent is killed. Both
        // are states, not animations, so they survive a scrub.
        state.castle = "fire";
        state.phase = "gone";
      } else {
        state.active = cue.target;
      }
    }
  }
  return state;
}

/**
 * Fill in each cue's index, label and clock. Called once per compiled run.
 *
 * A cue from a real run already knows when it happened (`at`, from the event's
 * offset). A demo cue does not, so it gets a synthetic clock accumulated from
 * the holds -- the console shows a timestamp either way, and it is always the
 * beat's own time rather than the wall clock of whenever you happened to press
 * play.
 */
export function finish(cues) {
  let clock = 0;
  cues.forEach((cue, i) => {
    cue.i = i;
    if (cue.at === undefined) cue.at = clock;
    clock = cue.at + (cue.hold || 0);
    // Stamp the log lines with their beat's time, so stepping back and
    // forward shows the same timestamps rather than re-dating the output.
    for (const entry of cue.log || []) {
      if (entry.at === undefined && entry.tag !== "cmd" && entry.tag !== "cmd-echo") {
        entry.at = cue.at;
      }
    }
    if (!cue.label) {
      cue.label = cue.breakout ? "breakout"
        : cue.respawn ? "recover"
        : cue.target ? (toolOf(cue.target) || cue.target)
        : cue.say ? (cue.say.tool || "think")
        : "log";
    }
  });
  return cues;
}