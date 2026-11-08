/* Sprite primitives shared by every screen.
 *
 * A sprite is a horizontal strip of frames. It plays inside a box one frame
 * wide: the strip <img> slides left a frame at a time with a stepped CSS
 * transform, so animation is compositor-only and costs React nothing.
 */
import htm from "/static/vendor/htm.js";

const { useState, useEffect } = React;
export const html = htm.bind(React.createElement);
export const SPRITES = "/static/sprites";

/** poyo.json: shared cell size, foot anchor, per-animation frames and fps. */
export function usePoyoManifest() {
  const [manifest, setManifest] = useState(null);
  useEffect(() => {
    let live = true;
    fetch(`${SPRITES}/poyo/poyo.json`)
      .then((r) => r.json())
      .then((m) => { if (live) setManifest(m); })
      .catch(() => { /* no Poyo is better than a broken page */ });
    return () => { live = false; };
  }, []);
  return manifest;
}

/**
 * One animated sprite at (x, y) in stage pixels, drawn at `scale`.
 * `once` plays the strip a single time and holds the last frame.
 * `reverse` (with once) plays it backwards and holds the first frame.
 * `holdEnd` shows the last frame, still.
 * `delay` (seconds) desynchronises props that share a loop.
 */
export function Sprite({
  src, w, h, frames, fps, x = 0, y = 0, scale, delay = 0, z, label, once = false, className = "",
  flip = false, reverse = false, holdEnd = false,
}) {
  if (flip) className += " flip";      // mirrored about the frame's centre
  if (holdEnd) {                       // a finished one-shot is its last frame
    once = true;
    delay = frames / fps;
  }
  const box = {
    left: `${x * scale}px`,
    top: `${y * scale}px`,
    width: `${w * scale}px`,
    height: `${h * scale}px`,
    zIndex: z ?? Math.round(y + h),
  };
  const strip = {
    width: `${w * frames * scale}px`,
    height: `${h * scale}px`,
    animationDuration: `${frames / fps}s`,
    // a one-shot stops ON the last frame, so it needs one step fewer
    animationTimingFunction: `steps(${once ? frames - 1 : frames})`,
    animationIterationCount: once ? 1 : "infinite",
    animationFillMode: once ? "both" : "none",
    animationDirection: reverse ? "reverse" : "normal",
    animationDelay: `${-delay}s`,
    animationPlayState: frames > 1 ? "running" : "paused",
    "--strip-end": once ? `${-((frames - 1) / frames) * 100}%` : "-100%",
  };
  return html`
    <div class=${`sprite ${className}`} style=${box}
         role=${label ? "img" : undefined} aria-label=${label}>
      <img key=${`${src}|${once}|${reverse}|${holdEnd}`} src=${src} alt="" draggable="false" style=${strip} />
    </div>`;
}
