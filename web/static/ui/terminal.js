/* The drill console: a real prompt you can type into.
 *
 * It reads like a terminal and it runs real commands, but it is not a shell.
 * `ares drill ...` is parsed here into the handful of typed fields the API
 * takes (see parseDrill); the text you typed is never sent anywhere to be
 * interpreted. A browser prompt that forwarded a string to a shell would be a
 * remote code execution hole with a pixel-art theme.
 *
 * What it can do depends on what the server admits to in /api/capabilities:
 *
 *   operator: false   the read-only viewer. `ares drill` prints the command
 *                     for you to run yourself and copies it to the clipboard,
 *                     then watches for the run to appear and attaches to it.
 *   operator: true    `python -m web.server --operator`. The same command is
 *                     POSTed, and the job's output streams back in here while
 *                     the scene plays the evidence as it lands.
 *
 * Output lines are typed out a few characters at a time, the way a CLI streams,
 * so the log keeps pace with the sandbox instead of dumping.
 */
import { html } from "/static/ui/sprite.js";

const { useState, useEffect, useRef, useCallback } = React;

const CHAR_MS = 9;        // typing tick
const LINE_PAUSE_MS = 70; // beat between lines, like a process flushing
const PROMPT = "C:\\ares>";

/** "mm:ss.s" from milliseconds since the run started. */
function clock(ms) {
  const s = Math.max(0, ms) / 1000;
  const m = Math.floor(s / 60);
  return `${String(m).padStart(2, "0")}:${(s % 60).toFixed(1).padStart(4, "0")}`;
}

const line = (tag, text) => ({ tag, text });

const HELP = [
  line("sys", "commands:"),
  line("", "  ares drill [recording] [--model ID] [--goal TEXT] [--no-kill]"),
  line("", "             [--max-steps N] [--max-tokens N] [--max-wall-seconds N]"),
  line("", "  runs                 list the runs with evidence on disk"),
  line("", "  open <run|latest>    replay that run in the sandbox"),
  line("", "  demo                 the scripted demo run"),
  line("", "  clear                clear this console"),
  line("", "  help                 this"),
  line("sys", "playback: the bar under the sandbox plays, pauses and steps through"),
  line("", "  whatever is loaded -- a demo, a recorded run, or a live drill."),
];

/* ---------------------------------------------------------------- parsing */

const FLAG_NUMBERS = {
  "--max-steps": "max_steps",
  "--max-tokens": "max_tokens",
  "--max-wall-seconds": "max_wall_seconds",
};

/** Split a command line on spaces, honouring "quoted strings". */
export function tokenize(text) {
  const out = [];
  const re = /"([^"]*)"|'([^']*)'|(\S+)/g;
  let m = re.exec(text);
  while (m) {
    out.push(m[1] ?? m[2] ?? m[3]);
    m = re.exec(text);
  }
  return out;
}

/**
 * `ares drill ...` -> { req, errors }.
 *
 * Only these flags exist. Anything else is an error rather than something
 * passed along, which is what keeps the request a set of fields instead of a
 * command: there is no argument here that can reach a shell.
 */
export function parseDrill(argv, recordings = []) {
  const req = {};
  const errors = [];
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    const next = () => {
      i += 1;
      if (i >= argv.length) { errors.push(`${a} needs a value`); return null; }
      return argv[i];
    };
    if (a === "--kill") req.kill = true;
    else if (a === "--no-kill") req.kill = false;
    else if (a === "--model") { const v = next(); if (v) req.model = v; }
    else if (a === "--goal") { const v = next(); if (v) req.goal = v; }
    else if (a in FLAG_NUMBERS) {
      const v = next();
      if (v !== null) {
        const n = Number(v);
        if (!Number.isInteger(n) || n <= 0) errors.push(`${a} wants a positive whole number, got ${v}`);
        else req[FLAG_NUMBERS[a]] = n;
      }
    } else if (a.startsWith("-")) {
      errors.push(`unknown option ${a}`);
    } else if (req.recording === undefined) {
      req.recording = a;
    } else {
      errors.push(`unexpected argument ${a}`);
    }
  }
  if (req.recording !== undefined && recordings.length && !recordings.includes(req.recording)) {
    errors.push(`unknown recording "${req.recording}"; one of: ${recordings.join(", ")}`);
  }
  return { req, errors };
}

/** The `ares drill` line a request is equivalent to, for the echo. */
export function drillCommand(req) {
  const parts = ["ares", "drill"];
  if (req.recording) parts.push(req.recording);
  if (req.model) parts.push("--model", req.model);
  if (req.goal) parts.push("--goal", JSON.stringify(req.goal));
  for (const [flag, key] of Object.entries(FLAG_NUMBERS)) {
    if (req[key] !== undefined) parts.push(flag, String(req[key]));
  }
  if (req.kill === false) parts.push("--no-kill");
  return parts.join(" ");
}

/* ---------------------------------------------------------------- rendering */

function Line({ entry, text }) {
  if (entry.tag === "cmd") {
    return html`<div class="ln ln-cmd"><span class="prompt">${PROMPT}</span> ${text}</div>`;
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

/**
 * `replay` is the log of the loaded run, up to the playback cursor -- so
 * stepping back in the sandbox shortens it, and what the console shows is
 * always what has happened *so far on screen*. `session` is this terminal's
 * own history: what you typed, and what the operator said back. The session
 * sits above the replay, because it is the frame around it.
 */
export function Terminal({ open, replay, session, onCommand, busy, caps }) {
  const lines = session.concat(replay);
  const [done, setDone] = useState(0);
  const [chars, setChars] = useState(0);
  const [input, setInput] = useState("");
  const [histAt, setHistAt] = useState(-1);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const [thumb, measure] = useThumb(bodyRef);

  const history = session.filter((e) => e.tag === "cmd").map((e) => e.text);

  // Stepping back shortens the log, so the typewriter's place in it can end up
  // past the end. Clamp rather than letting it index off the array.
  useEffect(() => {
    if (done > lines.length) { setDone(lines.length); setChars(0); }
  }, [lines.length, done]);

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

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const submit = (e) => {
    e.preventDefault();
    const text = input.trim();
    setInput("");
    setHistAt(-1);
    if (text) onCommand(text);
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      if (!history.length) return;
      e.preventDefault();
      const at = e.key === "ArrowUp"
        ? Math.min(history.length - 1, histAt + 1)
        : Math.max(-1, histAt - 1);
      setHistAt(at);
      setInput(at < 0 ? "" : history[history.length - 1 - at]);
    }
  };

  const shown = lines.slice(0, done);
  const typing = done < lines.length ? lines[done] : null;
  const caught = !typing;
  return html`
    <aside class=${`console ${open ? "console-open" : ""}`} aria-label="Drill console"
           aria-hidden=${!open}>
      <div class="console-inner">
        <header class="console-bar">
          ares -- drill console
          <span class=${`console-mode ${caps.operator ? "mode-op" : "mode-ro"}`}>
            ${caps.operator ? "operator" : "read-only"}
          </span>
        </header>
        <div class="console-scroll">
          <div class="console-body" ref=${bodyRef} onScroll=${measure} role="log"
               aria-live="polite">
            ${shown.map((e, i) => html`<${Line} key=${i} entry=${e} text=${e.text} />`)}
            ${typing && html`<${Line} entry=${typing} text=${(typing.text || "").slice(0, chars)} />`}
            ${caught && html`
              <form class="ln ln-input" onSubmit=${submit}>
                <span class="prompt">${PROMPT}</span>
                <input ref=${inputRef} class="console-input" value=${input} spellcheck="false"
                  autocomplete="off" aria-label="Type a command"
                  placeholder=${busy ? "a drill is running..." : ""}
                  onKeyDown=${onKeyDown}
                  onInput=${(e) => setInput(e.target.value)} />
              </form>`}
            ${!caught && html`<span class="cursor" aria-hidden="true"></span>`}
          </div>
          ${thumb && html`<div class="console-thumb" aria-hidden="true"
              style=${{ top: `${thumb.top}px`, height: `${thumb.h}px` }}></div>`}
        </div>
      </div>
    </aside>`;
}

export { HELP, line };
