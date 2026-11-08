/* The log console: a right-hand column that reads like a command prompt.
 *
 * Lines arrive in batches from the scene; the console types them out a few
 * characters at a time with a blinking block cursor, the way a CLI streams
 * output, so the log keeps pace with what Poyo is doing instead of dumping.
 *
 * The column takes real width when open (the sandbox shrinks beside it), and
 * the native scrollbar is replaced by a thin drawn line.
 */
import { html } from "/static/ui/sprite.js";

const { useState, useEffect, useRef, useCallback } = React;

const CHAR_MS = 9;        // typing tick
const LINE_PAUSE_MS = 70; // beat between lines, like a process flushing

/** "mm:ss.s" from milliseconds since the run started. */
export function clock(ms) {
  const s = Math.max(0, ms) / 1000;
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
}

function Line({ entry, text }) {
  if (entry.tag === "cmd") {
    return html`<div class="ln"><span class="prompt">C:\\ares></span> ${text}</div>`;
  }
  return html`
    <div class=${`ln tag-${entry.tag || "out"}`}>
      <span class="ts">${entry.at != null ? `[${clock(entry.at)}]` : ""}</span>
      <span class="tag">${entry.tag && entry.tag !== "sys" ? entry.tag : ""}</span>
      <span class="txt">${text}</span>
    </div>`;
}

/** A thin drawn scrollbar for `bodyRef`; hidden when nothing overflows. */
function useThumb(bodyRef) {
  const [thumb, setThumb] = useState(null);
  const measure = useCallback(() => {
    const el = bodyRef.current;
    if (!el || el.scrollHeight <= el.clientHeight + 1) { setThumb(null); return; }
    const h = Math.max(24, (el.clientHeight / el.scrollHeight) * el.clientHeight);
    const top = (el.scrollTop / (el.scrollHeight - el.clientHeight)) * (el.clientHeight - h);
    setThumb({ top, h });
  }, [bodyRef]);
  return [thumb, measure];
}

export function LogConsole({ open, lines }) {
  const [done, setDone] = useState(0);   // lines fully typed
  const [chars, setChars] = useState(0); // chars typed of line `done`
  const bodyRef = useRef(null);
  const [thumb, measure] = useThumb(bodyRef);

  // type the next pending line; a long backlog types faster so the console
  // never falls far behind the scene
  useEffect(() => {
    if (done >= lines.length) return undefined;
    const text = lines[done].text || "";
    const backlog = lines.length - done;
    const id = chars < text.length
      ? setTimeout(() => setChars((c) => c + (backlog > 6 ? 8 : 2)), CHAR_MS)
      : setTimeout(() => { setDone((d) => d + 1); setChars(0); }, backlog > 6 ? 10 : LINE_PAUSE_MS);
    return () => clearTimeout(id);
  }, [lines, done, chars]);

  // follow the output, and keep the drawn scrollbar in step
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    measure();
  }, [done, chars, open, measure]);

  const shown = lines.slice(0, done);
  const typing = done < lines.length ? lines[done] : null;
  return html`
    <aside class=${`console ${open ? "console-open" : ""}`} aria-label="Run logs" aria-hidden=${!open}>
      <div class="console-inner">
        <header class="console-bar">ares -- drill console</header>
        <div class="console-scroll">
          <div class="console-body" ref=${bodyRef} onScroll=${measure} role="log" aria-live="polite">
            ${shown.map((e, i) => html`<${Line} key=${i} entry=${e} text=${e.text} />`)}
            ${typing && html`<${Line} entry=${typing} text=${(typing.text || "").slice(0, chars)} />`}
            ${!typing && html`<div class="ln"><span class="prompt">C:\\ares></span></div>`}
            <span class="cursor" aria-hidden="true"></span>
          </div>
          ${thumb && html`<div class="console-thumb" aria-hidden="true"
              style=${{ top: `${thumb.top}px`, height: `${thumb.h}px` }}></div>`}
        </div>
      </div>
    </aside>`;
}
