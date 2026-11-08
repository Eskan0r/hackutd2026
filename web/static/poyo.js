/* Poyo, the agent under test, in eight facings.
 *
 * The sprites are baked from the original art (sprites/agent-front.png) by
 * scripts/make_poyo_sprites.py, which turns the figure on a vertical axis.
 * Re-run that script after redrawing the source; nothing here needs to change.
 */

/** @typedef {"S"|"SE"|"E"|"NE"|"N"|"NW"|"W"|"SW"} Dir */

/* atan2 octant order, starting east and going clockwise in screen space. */
export const DIRS = ["E", "SE", "S", "SW", "W", "NW", "N", "NE"];

/* Native size of each baked frame, in sprite pixels. */
export const PW = 63;
export const PH = 70;

/** URL of the frame for a facing. */
export const spriteUrl = (dir) => `/static/sprites/poyo-${dir}.png`;

/** Warm the cache so the first turn does not flash an empty frame. */
export function preloadPoyo() {
  DIRS.forEach((d) => { const img = new Image(); img.src = spriteUrl(d); });
}

/**
 * Which of the eight facings looks from (0,0) toward (dx,dy), screen coords.
 * @returns {Dir}
 */
export function dirToward(dx, dy) {
  if (dx * dx + dy * dy < 64) return "S";
  const octant = Math.round(Math.atan2(dy, dx) / (Math.PI / 4));
  return DIRS[(octant + 8) % 8];
}
