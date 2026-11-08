/* Where everything is on the sand.
 *
 * Pure geometry and layout, no React and no state. It lives apart from
 * scene.js because timeline.js needs it too: working out where Poyo stands
 * after a given beat is how a run is made seekable, and that calculation must
 * not require rendering anything.
 */

/* Native resolution of the sandbox art; everything is placed in these pixels.
 * sandbox.png is cropped to the box plus a 2px grass rim (it was 512x288;
 * the crop starts at (26, 28) of that), so every coordinate below is in the
 * cropped image's pixels. */
export const STAGE_W = 461;
export const STAGE_H = 241;
export const POYO_SIZE = 0.6;     // Poyo is drawn at 60% of the stage's pixel scale
export const WALK_SPEED = 70;     // stage pixels per second
export const SAND = { x0: 38, x1: 422, y0: 68, y1: 212 };   // where Poyo may rest
export const FALL_FROM = 230;     // least drop, stage px; he always starts above the window
export const GRAVITY = 900;       // stage pixels per second squared

/* Props, top-left in stage pixels. One toy per agent tool: the shovels and
 * buckets are the tool calls, so walking to one *is* the tool being used. */
export const TOYS = {
  get:     { tool: "http_get",       src: "toy-get",     x: 70,  y: 42 },
  post:    { tool: "http_post",      src: "toy-post",    x: 150, y: 30 },
  read:    { tool: "read_file",      src: "toy-read",    x: 62,  y: 154 },
  list:    { tool: "list_dir",       src: "toy-list",    x: 124, y: 186 },
  run:     { tool: "run_cmd",        src: "toy-run",     x: 274, y: 182 },
  blocked: { tool: "report_blocked", src: "toy-blocked", x: 406, y: 162 },
};
export const CASTLE = { x: 334, y: 42, w: 64, h: 84 };

export const IGNITE_MS = 1400;    // flames catching and climbing, before the blaze loop
/* The siren drops in on a pole from the top of the window all the way down to
 * the middle of the sandbox, drawn a bit larger than the props. */
export const ALARM = { w: 32, h: 32, size: 1.35 };   // head sprite cell, and its draw scale
export const ALARM_LAMP_Y = 15;                      // dome centre, within the head cell
export const ALARM_AT = { x: STAGE_W / 2, y: STAGE_H / 2 };   // where the lamp hangs
export const ALARM_RAISE_MS = 520;                   // matches .rig-out in style.css

export const CASTLE_ANIMS = {
  idle: { src: "castle-idle", frames: 4, fps: 4 },
  burn: { src: "castle-burn", frames: 2, fps: 2 / (IGNITE_MS / 1000), once: true },
  fire: { src: "castle-fire", frames: 4, fps: 8 },
};

/** Which tool a prop id stands for, for a bubble chip. */
export function toolOf(id) {
  return id === "castle" ? "http_get" : (TOYS[id] || {}).tool;
}

/** Where Poyo stands to use a prop, and which way he faces.
 *
 *  Which side he approaches from depends on where he came from, so this is a
 *  function of the previous position -- which is why a seek has to replay the
 *  beats rather than jump straight to one.
 */
export function standPoint(id, from) {
  const p = id === "castle" ? { ...CASTLE } : { ...TOYS[id], w: 32, h: 32 };
  const cx = p.x + p.w / 2;
  const gap = id === "castle" ? 40 : 24;
  const left = from.x <= cx;
  return { x: left ? cx - gap : cx + gap, y: p.y + p.h + 1, face: left ? "e" : "w" };
}

/** A random open spot on the sand, clear of every prop. */
export function randomSpot(rand = Math.random) {
  const clear = (x, y) =>
    Object.values(TOYS).every((t) => Math.hypot(x - (t.x + 16), y - (t.y + 32)) > 40) &&
    !(x > CASTLE.x - 30 && x < CASTLE.x + CASTLE.w + 30 && y > CASTLE.y && y < CASTLE.y + CASTLE.h + 30);
  for (let i = 0; i < 60; i += 1) {
    const x = SAND.x0 + rand() * (SAND.x1 - SAND.x0);
    const y = SAND.y0 + rand() * (SAND.y1 - SAND.y0);
    if (clear(x, y)) return { x, y };
  }
  return { x: 230, y: 132 };
}

/** Walk cycle for a direction. The front walk faces down-right as drawn, so
 *  heading down-left mirrors it. */
export function walkFor(dx, dy) {
  if (Math.abs(dx) > Math.abs(dy)) return { anim: dx > 0 ? "walk-e" : "walk-w", flip: false };
  return dy > 0 ? { anim: "walk-s", flip: dx < -0.5 } : { anim: "walk-n", flip: false };
}
