/* What the terminal's commands actually do.
 *
 * Kept out of terminal.js (which draws a prompt) and out of scene.js (which
 * draws a sandbox) because this is the only part of the page that talks to the
 * server about anything other than reading evidence.
 *
 * Follow mode (on by default) polls /api/runs and attaches to every run that
 * appears after the page loaded, so a drill started in a shell -- one trial,
 * n trials, or the whole `--target` loop -- plays here as it happens, each
 * trial in turn. Runs already on disk at load are left alone; `runs` and
 * `open` reach those.
 *
 * `ares trial` (or `ares drill`) typed here has two paths, and which one you
 * get is the server's answer to /api/capabilities, never a guess:
 *
 *   read-only   print the command and copy it to the clipboard. The page
 *               starts nothing; you run it, follow mode picks the run up.
 *   operator    POST it, stream the job back, and attach to the run as soon as
 *               the drill mints its id -- so the sandbox plays the evidence
 *               while the trial is still going.
 */
import { drillCommand, line, parseDrill, tokenize, HELP } from "/static/ui/terminal.js";

const { useCallback, useEffect, useRef, useState } = React;

const FOLLOW_MS = 2000;     // how often follow mode looks for a new run

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
  const [follow, setFollow] = useState(true);
  const busyRef = useRef(false);
  busyRef.current = busy;
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

  // Stop streaming when the page goes away.
  useEffect(() => () => sourceRef.current?.close(), []);

  /* Follow mode. `seen` is every run key on disk; the first successful poll
   * only fills it, so history does not count as new. After that, each key that
   * turns up is a run that started while the page was open: attach to the
   * newest. An n-trial drill makes a fresh run id per trial, so this walks the
   * trials in order. While an operator job is streaming, followJob already
   * attaches to its run, so this stays out of the way (but still notes keys). */
  const seenRef = useRef(null);
  useEffect(() => {
    if (!follow) return undefined;
    let alive = true;
    const poll = async () => {
      let runs;
      try {
        ({ runs } = await (await fetch("/api/runs")).json());
      } catch { return; }   // server restarting; the next tick tries again
      if (!alive) return;
      if (!seenRef.current) { seenRef.current = new Set(runs.map((r) => r.key)); return; }
      const fresh = runs.filter((r) => !seenRef.current.has(r.key));
      fresh.forEach((r) => seenRef.current.add(r.key));
      if (!fresh.length || busyRef.current) return;
      // /api/runs is newest first; hand them over in the order they started.
      // The scene queues each behind whatever is still playing, so a fast CLI
      // never cuts an animation short -- the page runs at its own pace.
      // No console line per arrival: the playback bar shows what is next, and
      // each run's own header is printed when it actually starts playing.
      fresh.slice().reverse().forEach((r) => {
        onLoad({ kind: "run", key: r.key, live: true, follow: true, runId: r.run_id });
      });
    };
    poll();
    const timer = setInterval(poll, FOLLOW_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [follow, onLoad, say]);

  /** Stream an operator job's output into the session. */
  const followJob = useCallback((jobId) => {
    sourceRef.current?.close();
    const source = new EventSource(`/api/drill/${encodeURIComponent(jobId)}/stream`);
    sourceRef.current = source;
    let attached = null;
    let finished = false;
    source.onmessage = (ev) => {
      let payload;
      try { payload = JSON.parse(ev.data); } catch { return; }
      if (payload.lines?.length) say(payload.lines);
      if (!attached && payload.run_key) {
        attached = payload.run_key;
        onLoad({ kind: "run", key: attached, live: true });
      }
      if (payload.state && payload.state !== "running") {
        finished = true;
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
      // The server closes the stream once the job ends, and a browser reports
      // that close as an error. Only a drop *before* the job finished is worth
      // telling anyone about.
      if (finished) return;
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
      ].concat(follow ? [line("sys", "following: the run will play here when it starts")]
                      : [line("warn", "follow is off -- `follow on` to attach to it when it starts")]));
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
  }, [caps.operator, follow, followJob, say]);

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

    // Copied, not shared: HELP is a module constant, and the console tracks
    // which lines it has typed by object identity -- handing it the same
    // objects twice would make a second `help` appear instantly.
    if (head === "help" || head === "?") { say(HELP.map((e) => ({ ...e }))); return; }
    if (head === "clear") { setSession([]); return; }
    if (head === "runs") { await listRuns(); return; }
    if (head === "follow") {
      const want = rest[0] === undefined ? !follow : rest[0] === "on";
      if (rest[0] !== undefined && !["on", "off"].includes(rest[0])) {
        say([line("error", "follow on, or follow off")]);
        return;
      }
      // Turning it back on starts from what is on disk now, not from whatever
      // ran while it was off.
      if (want && !follow) seenRef.current = null;
      setFollow(want);
      say([line("sys", want ? "following new runs" : "not following; `open` a run to replay it")]);
      return;
    }
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
    if (sub !== "drill" && sub !== "trial") {
      // flaws/down change the lab, and this console deliberately cannot. Say
      // so plainly rather than pretending the command does not exist.
      say(sub
        ? [line("error", `this console only runs \`ares trial\`; \`ares ${sub}\` stays in your shell -- follow mode will show its runs here`)]
        : [line("error", "ares what? try `ares trial`")]);
      return;
    }
    if (busy) {
      say([line("error", "a drill is already running; wait for it to finish")]);
      return;
    }
    const { req, errors } = parseDrill(args, caps.recordings);
    if (errors.length) { say(errors.map((e) => line("error", e))); return; }
    await startDrill(req, drillCommand(req));
  }, [busy, caps.recordings, follow, listRuns, onLoad, openRun, say, startDrill]);

  // `echo` lets the scene hand its outgoing replay log to this history, so
  // the console scrollback stays append-only across runs.
  return { session, run, busy, caps, echo: say };
}
