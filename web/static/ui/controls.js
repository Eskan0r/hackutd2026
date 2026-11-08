/* The transport bar: restart, step back, play/pause, step forward, scrubber.
 *
 * Icons are drawn as pixel rectangles rather than glyphs, for the same reason
 * the canvas draws no text: a 7px font upscaled with image-rendering: pixelated
 * is mush. These are crisp at any scale.
 *
 * Buttons only move the cursor (see transport.js). Nothing here can start,
 * stop or alter a drill -- the bar is a viewer control, not a kill switch.
 */
import { html } from "/static/ui/sprite.js";

const Icon = ({ children }) => html`
  <svg viewBox="0 0 12 12" class="tc-icon" aria-hidden="true"
       shape-rendering="crispEdges">${children}</svg>`;

const bar = (x, y, w, h) => html`<rect x=${x} y=${y} width=${w} height=${h} fill="currentColor" />`;

/* A pixel triangle: a stack of rows, widest at the base. `dir` 1 points right. */
function tri(x0, dir = 1) {
  const rows = [];
  for (let i = 0; i < 4; i += 1) {
    const x = dir > 0 ? x0 + i : x0 + 3 - i;
    rows.push(html`<rect key=${i} x=${x} y=${2 + i} width="1" height=${8 - i * 2}
                          fill="currentColor" />`);
  }
  return rows;
}

const IconPlay = () => html`<${Icon}>${tri(4, 1)}<//>`;
const IconPause = () => html`<${Icon}>${bar(3, 2, 2, 8)}${bar(7, 2, 2, 8)}<//>`;
const IconBack = () => html`<${Icon}>${bar(2, 2, 2, 8)}${tri(5, -1)}<//>`;
const IconForward = () => html`<${Icon}>${tri(3, 1)}${bar(8, 2, 2, 8)}<//>`;
const IconRestart = () => html`<${Icon}>${bar(2, 2, 2, 8)}${tri(5, -1)}${bar(9, 2, 1, 8)}<//>`;

function Button({ onClick, disabled, title, children, wide }) {
  return html`
    <button class=${`tc-btn ${wide ? "tc-btn-wide" : ""}`} type="button" onClick=${onClick}
            disabled=${disabled} title=${title} aria-label=${title}>
      ${children}
    </button>`;
}

/**
 * `t` is the useTransport handle. `label` is what the current beat is doing,
 * shown as text so it stays readable at any zoom.
 */
export function Controls({ t, label, source }) {
  const at = t.cursor + 1;             // 1-based for humans; 0 = not started
  return html`
    <div class="transport" role="group" aria-label="Playback">
      <${Button} onClick=${t.restart} disabled=${t.atStart} title="Back to the start">
        <${IconRestart} />
      <//>
      <${Button} onClick=${t.back} disabled=${t.atStart} title="Step back one beat">
        <${IconBack} />
      <//>
      <${Button} onClick=${t.toggle} wide=${true}
                 title=${t.playing ? "Pause" : t.atEnd ? "Replay from the start" : "Play"}>
        ${t.playing ? html`<${IconPause} />` : html`<${IconPlay} />`}
      <//>
      <${Button} onClick=${t.forward} disabled=${t.atEnd} title="Step forward one beat">
        <${IconForward} />
      <//>
      <label class="tc-scrub">
        <span class="tc-count">${at}/${t.length}</span>
        <input type="range" min="-1" max=${t.length - 1} value=${t.cursor} step="1"
               aria-label="Scrub through the run"
               onInput=${(e) => t.seek(Number(e.target.value))} />
      </label>
      <span class="tc-now">
        ${label ? html`<span class="tc-beat">${label}</span>` : null}
        <span class="tc-source">${source}</span>
      </span>
    </div>`;
}
