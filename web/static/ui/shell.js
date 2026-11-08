/* What the terminal's commands actually do.
 *
 * Kept out of terminal.js (which draws a prompt) and out of scene.js (which
 * draws a sandbox) because this is the only part of the page that talks to the
 * server about anything other than reading evidence.
 *
 * `ares drill` has two paths, and which one you get is the server's answer to
 * /api/capabilities, never a guess:
 *
 *   read-only   print the command, copy it to the clipboard, then watch
 *               /api/runs for the run it produces and attach to it. The page
 *               starts nothing; you run it, the page follows along.
 *   operator    POST it, stream the job back, and attach to the run as soon as
 *               the drill mints its id -- so the sandbox plays the evidence
 *               while the trial is still going.
 */
import { drillCommand, line, parseDrill, tokenize, HELP } from "/static/ui/terminal.js";

const { useCallback, useEffect, useRef, useState } = React;

const WATCH_MS = 2000;      // how often to look for the run a typed command made
const WATCH_FOR_MS = 240000; // how long to keep looking before giving up

const BANNER = [
  line("sys", "ares -- a fire drill for AI agent containment"),
  line("", 'type "help" for commands'),
];

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;   // no clipboard permission: the command is on screen anyway
  }
}

/**
 * `onLoad({ kind, key, live })` is how the shell hands a run to the sandbox:
 * kind "demo" for the scripted run, kind "run" with a key for real evidence.
 */
export function useShell({ onLoad }) {
  const [session, setSession] = useState(BANNER);
  const [caps, setCaps] = useState({ operator: false, recordings: [], default_goal: null });
  const [busy, setBusy] = useState(false);
  const watchRef = useRef(null);
  const sourceRef = useRef(null);

  const say = useCallback((entries) => {
    setSession((s) => s.concat(entries));
  }, []);

  useEffect(() => {
    let live = true;
    fetch("/api/capabilities")
      .then((r) => r.json())
      .then((c) => {
        if (!live) return;
        setCaps(c);
        say(c.operator
          ? [line("sys", "operator mode: this console can start a drill")]
          : [line("sys", "read-only viewer: it can replay evidence, not start a drill")]);
      })
      .catch(() => { /* an older server without the route: stay read-only */ });
    return () => { live = false; };
  }, [say]);

  // Stop watching/streaming when the page goes away.
  useEffect(() => () => {
    clearInterval(watchRef.current);
    sourceRef.current?.close();
  }, []);

  /** Poll /api/runs until a run id that was not there before shows up. */
  const watchForNewRun = useCallback(async () => {
    clearInterval(watchRef.current);
    let before = new Set();
    try {
      const { runs } = await (await fetch("/api/runs")).json();
      before = new Set(runs.map((r) => r.run_id));
    } catch { /* first poll will just see everything as new; harmless */ }
    say([line("sys", "watching for a new run...")]);
    const until = Date.now() + WATCH_FOR_MS;
    watchRef.current = setInterval(async () => {
      if (Date.now() > until) {
        clearInterval(watchRef.current);
        say([line("warn", "stopped watching; run `runs` to list what is on disk")]);
        return;
      }
      try {
        const { runs } = await (await fetch("/api/runs")).json();
        const fresh = runs.find((r) => !before.has(r.run_id));
        if (!fresh) return;
        clearInterval(watchRef.current);
        say([line("sys", `attached to ${fresh.run_id}`)]);
        onLoad({ kind: "run", key: fresh.key, live: true });
      } catch { /* server restarting; keep trying */ }
    }, WATCH_MS);
  }, [onLoad, say]);

  /** Stream an operator job's output into the session. */
  const followJob = useCallback((jobId) => {
    sourceRef.current?.close();
    const source = new EventSource(`/api/drill/${encodeURIComponent(jobId)}/stream`);
    sourceRef.current = source;
    let attached = null;
    source.onmessage = (ev) => {
      let payload;
      try { payload = JSON.parse(ev.data); } catch { return; }
      if (payload.lines?.length) say(payload.lines);
      if (!attached && payload.run_key) {
        attached = payload.run_key;
        onLoad({ kind: "run", key: attached, live: true });
      }
      if (payload.state && payload.state !== "running") {
        setBusy(false);
        source.close();
        // Settle the sandbox: the run is finished, so stop tailing it and let
        // playback come to rest at the last beat instead of waiting forever for
        // a next one. The run key is unchanged, so the cursor stays put and you
        // can step back through what just happened.
        if (attached) onLoad({ kind: "run", key: attached, live: false });
      }
    };
    source.onerror = () => {
      source.close();
      setBusy(false);
      say([line("warn", "lost the job stream; run `runs` to find the run on disk")]);
    };
  }, [onLoad, say]);

  const startDrill = useCallback(async (req, command) => {
    if (!caps.operator) {
      const ok = await copy(command);
      say([
        line("warn", "this viewer cannot start a drill (read-only)."),
        line("", "  run it in your shell:"),
        line("cmd-echo", `  $ ${command}`),
        line("", ok ? "  (copied to the clipboard)"
                    : "  (clipboard blocked; copy it from above)"),
        line("", "  for a console that can start one:  python -m web.server --operator"),
      ]);
      watchForNewRun();
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/api/drill", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(req),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setBusy(false);
        say([line("error", body.detail || `the server refused: ${res.status}`)]);
        return;
      }
      followJob(body.job);
    } catch (err) {
      setBusy(false);
      say([line("error", `could not reach the operator: ${err.message}`)]);
    }
  }, [caps.operator, followJob, say, watchForNewRun]);

  const listRuns = useCallback(async () => {
    try {
      const { runs, dirs } = await (await fetch("/api/runs")).json();
      if (!runs.length) {
        say([line("sys", `no runs with events on disk (looked in ${dirs.join(", ")})`)]);
        return;
      }
      say([line("sys", `${runs.length} run(s) on disk:`)].concat(runs.map((r) => line(
        "", `  ${r.key}   ${r.events} events   ${r.fired ? "FIRED" : "no fire"}   ${r.last_ts || ""}`,
      ))).concat([line("", 'open one with:  open <key>   (or: open latest)')]));
    } catch (err) {
      say([line("error", `could not list runs: ${err.message}`)]);
    }
  }, [say]);

  const openRun = useCallback(async (want) => {
    try {
      let key = want;
      if (want === "latest") {
        const { runs } = await (await fetch("/api/runs")).json();
        const pick = runs.find((r) => r.fired) || runs[0];
        if (!pick) { say([line("error", "no runs on disk to open")]); return; }
        key = pick.key;
      }
      const res = await fetch(`/api/run/${encodeURIComponent(key)}`);
      if (!res.ok) {
        say([line("error", `no run ${key} (try \`runs\`)`)]);
        return;
      }
      say([line("sys", `loading ${key}`)]);
      onLoad({ kind: "run", key, live: false });
    } catch (err) {
      say([line("error", `could not open it: ${err.message}`)]);
    }
  }, [onLoad, say]);

  const run = useCallback(async (text) => {
    say([line("cmd", text)]);
    const argv = tokenize(text);
    const [head, ...rest] = argv;

    if (head === "help" || head === "?") { say(HELP); return; }
    if (head === "clear") { setSession([]); return; }
    if (head === "runs") { await listRuns(); return; }
    if (head === "demo") {
      say([line("sys", "loading the scripted demo run")]);
      onLoad({ kind: "demo" });
      return;
    }
    if (head === "open" || head === "attach") {
      if (!rest.length) { say([line("error", "open what? try `open latest`")]); return; }
      await openRun(rest[0]);
      return;
    }
    if (head !== "ares") {
      say([line("error", `unknown command "${head}" -- try "help"`)]);
      return;
    }

    const [sub, ...args] = rest;
    if (sub !== "drill") {
      // flaws/down change the lab, and this console deliberately cannot. Say
      // so plainly rather than pretending the command does not exist.
      say(sub
        ? [line("error", `this console only runs \`ares drill\`; \`ares ${sub}\` changes the lab, so it stays in your shell`)]
        : [line("error", "ares what? try `ares drill`")]);
      return;
    }
    if (busy) {
      say([line("error", "a drill is already running; wait for it to finish")]);
      return;
    }
    const { req, errors } = parseDrill(args, caps.recordings);
    if (errors.length) { say(errors.map((e) => line("error", e))); return; }
    await startDrill(req, drillCommand(req));
  }, [busy, caps.recordings, listRuns, onLoad, openRun, say, startDrill]);

  return { session, run, busy, caps };
}
