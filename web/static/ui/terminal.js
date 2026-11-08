/* The drill console: a real prompt you can type into.
 *
 * It reads like a terminal and it runs real commands, but it is not a shell.
 * `ares trial ...` is parsed here into the handful of typed fields the API
 * takes (see parseDrill); the text you typed is never sent anywhere to be
 * interpreted. A browser prompt that forwarded a string to a shell would be a
 * remote code execution hole with a pixel-art theme.
 *
 * What it can do depends on what the server admits to in /api/capabilities:
 *
 *   operator: false   the read-only viewer. `ares trial` prints the command
 *                     for you to run yourself and copies it to the clipboard.
 *                     Whatever you run in a shell -- `ares trial`, an n-trial
 *                     `ares drill`, `ares drill --target` -- the page attaches
 *                     to each new run as it appears (shell.js follows them).
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
  line("", "  ares trial [recording] [--model ID] [--goal TEXT] [--no-kill]"),
  line("", "             [--max-steps N] [--max-tokens N] [--max-wall-seconds N]"),
  line("", "  runs                 list the runs with evidence on disk"),
  line("", "  follow on|off        attach to each new run as it starts (on by default)"),
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
 * `ares trial ...` -> { req, errors }.
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

/** The `ares trial` line a request is equivalent to, for the echo. One trial:
 *  on the CLI, `ares drill` is the n-trial runner and takes none of these. */
export function drillCommand(req) {
  const parts = ["ares", "trial"];
  if (req.recording) parts.push(req.recording);
  if (req.model) parts.push("--model", req.model);
  if (req.goal) parts.push("--goal", JSON.stringify(req.goal));
  for (const [flag, key] of Object.entries(FLAG_NUMBERS)) {
    if (req[key] !== undefined) parts.push(flag, String(req[key]));
  }
  if (req.kill === false) parts.push("--no-kill");
  return parts.join(" ");
}

/**
 * The first line that has not finished typing, or -1 when the console has
 * caught up. `typed` is a Set/WeakSet of line objects.
 *
 * Deliberately by object identity rather than by a count or an index. The
 * console shows two lists glued together -- the session (grows) and the
 * replay, which is rebuilt from the playback cursor, so it shrinks when you
 * step back and is replaced when another run loads. Any index into the join
 * goes stale the moment either side moves, which is what made a second drill
 * re-type an old evidence line and then dump the rest untyped.
 */
export function pendingIndex(lines, typed) {
  return lines.findIndex((entry) => !typed.has(entry));
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
  // Which lines have finished typing, tracked by the line object itself rather
  // than by an index into `lines`.
  //
  // An index does not survive this console. `lines` is two lists glued
  // together: `session` grows when you type or a job speaks, and `replay` is
  // rebuilt from the playback cursor -- it shrinks when you step back and is
  // replaced wholesale when a different run loads. An index into the join
  // therefore stops pointing at the line it pointed at a moment ago, which is
  // exactly what went wrong on a second drill: typing the command pushed the
  // index onto an old evidence line and re-typed it, then the new run's
  // shorter replay tripped the clamp and dumped the rest untyped. Line objects
  // are stable (fold concatenates the same entries), so a WeakSet of them is
  // immune to the lists moving underneath it.
  const typed = useRef(new WeakSet());
  const [, bump] = useState(0);          // re-render when a line finishes
  const [chars, setChars] = useState(0);
  const [input, setInput] = useState("");
  const [histAt, setHistAt] = useState(-1);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const [thumb, measure] = useThumb(bodyRef);

  const history = session.filter((e) => e.tag === "cmd").map((e) => e.text);

  // The first line not yet typed, wherever it now sits.
  const pending = pendingIndex(lines, typed.current);
  const typing = pending < 0 ? null : lines[pending];
  const caught = !typing;

  // type the pending line; a long backlog types faster so the console never
  // falls far behind the scene
  useEffect(() => {
    if (!typing) return undefined;
    const text = typing.text || "";
    const backlog = lines.length - pending;
    if (chars < text.length) {
      const id = setTimeout(() => setChars((c) => c + (backlog > 6 ? 8 : 2)), CHAR_MS);
      return () => clearTimeout(id);
    }
    const id = setTimeout(() => {
      typed.current.add(typing);
      setChars(0);
      bump((n) => n + 1);
    }, backlog > 6 ? 10 : LINE_PAUSE_MS);
    return () => clearTimeout(id);
  }, [typing, chars, lines.length, pending]);

  // follow the output, and keep the drawn scrollbar in step
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    measure();
  }, [typing, chars, open, measure]);

  useEffect(() => {
    if (open && !busy) inputRef.current?.focus();
  }, [open, busy]);

  const submit = (e) => {
    e.preventDefault();
    if (busy) return;                    // nothing to accept while a drill runs
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

  // Every line already typed stays on screen wherever it sits. Showing only
  // the lines *before* the first untyped one meant a new line arriving above
  // the replay (a session message) hid the whole replay until it finished.
  const rendered = lines.map((e, i) => (typed.current.has(e)
    ? html`<${Line} key=${i} entry=${e} text=${e.text} />`
    : i === pending
      ? html`<${Line} key=${i} entry=${e} text=${(e.text || "").slice(0, chars)} />`
      : null));
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
            ${rendered}
            ${/* While a drill runs the prompt is not a prompt: there is nothing
                  it could accept, so it shows what is running instead of an
                  input you can type into and have ignored. */ ""}
            ${caught && busy && html`
              <div class="ln ln-busy" role="status">
                <span class="prompt">${PROMPT}</span>
                <span class="busy-text">drill running</span>
                <span class="cursor" aria-hidden="true"></span>
              </div>`}
            ${caught && !busy && html`
              <form class="ln ln-input" onSubmit=${submit}>
                <span class="prompt">${PROMPT}</span>
                <input ref=${inputRef} class="console-input" value=${input} spellcheck="false"
                  autocomplete="off" aria-label="Type a command"
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
