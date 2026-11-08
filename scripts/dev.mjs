// npm run dev -- the dashboard and a drill, in one command.
//
//   npm run dev                         drill ARES_TARGET from .env, live agent (ARES_MODEL)
//   npm run dev -- --target o/r --mode scripted     anything after -- goes to `ares hunt`
//   npm run dashboard                   just the dashboard (same as --no-drill)
//
// The dashboard comes up first and the browser opens on it, so its follow mode
// is already watching when the drill writes its first event -- it only picks
// up runs that start after the page loads. Its request log goes to
// .ares-dev/web.log: it polls every two seconds, and that would bury the
// drill's own output. When the drill ends the dashboard stays up (the page
// plays at its own pace and may still be catching up); Ctrl+C stops both.
import { spawn } from "node:child_process";
import { mkdirSync, openSync } from "node:fs";
import { join } from "node:path";
import {
  IS_WIN, REPO, bad, cyan, hasVenv, readEnvFile, todo, venvBin, yellow,
} from "./venv.mjs";

const argv = process.argv.slice(2);
const noDrill = argv.includes("--no-drill");
const noOpen = argv.includes("--no-open");
const drillArgs = argv.filter((a) => a !== "--no-drill" && a !== "--no-open");

const fileEnv = readEnvFile();
const port = process.env.ARES_WEB_PORT || fileEnv.ARES_WEB_PORT || "8090";
const url = `http://127.0.0.1:${port}/`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

if (!hasVenv()) {
  bad("no .venv yet: run `npm run setup` first");
  process.exit(1);
}

/** The `ares hunt` arguments: whatever came after `--`, else ARES_TARGET. */
function drillArgv() {
  if (drillArgs.length) return ["hunt", ...drillArgs];
  const target = process.env.ARES_TARGET || fileEnv.ARES_TARGET;
  if (!target) {
    bad("nothing to drill: set ARES_TARGET=owner/repo in .env, or pass arguments,");
    console.log("    e.g.  npm run dev -- --target owner/repo --mode live");
    console.log("    or    npm run dashboard   (just the viewer)");
    process.exit(1);
  }
  // `hunt` stops at the first breakout and takes it through fix -> replay -> PR.
  return ["hunt", "--target", target, "--mode", process.env.ARES_MODE || fileEnv.ARES_MODE || "live"];
}

async function dashboardUp() {
  try { return (await fetch(`${url}api/runs`)).ok; } catch { return false; }
}

function openBrowser() {
  if (noOpen) return;
  const [cmd, args] = IS_WIN ? ["cmd", ["/c", "start", "", url]]
    : process.platform === "darwin" ? ["open", [url]] : ["xdg-open", [url]];
  spawn(cmd, args, { stdio: "ignore", detached: true }).on("error", () => {}).unref();
}

const children = [];
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) if (child.exitCode === null) child.kill();
  process.exit(code);
}
process.on("SIGINT", () => stop(130));
process.on("SIGTERM", () => stop(143));

async function startDashboard() {
  if (await dashboardUp()) {
    console.log(`  dashboard already running at ${cyan(url)} -- using it`);
    return;
  }
  mkdirSync(join(REPO, ".ares-dev"), { recursive: true });
  const log = openSync(join(REPO, ".ares-dev", "web.log"), "a");
  const web = spawn(venvBin("python"), ["-m", "web.server", "--port", port], {
    cwd: REPO, stdio: ["ignore", log, log],
  });
  children.push(web);
  web.on("exit", (code) => {
    if (stopping) return;
    bad(`the dashboard exited (code ${code}); see .ares-dev/web.log`);
    stop(code || 1);
  });
  for (let i = 0; i < 60; i += 1) {
    if (await dashboardUp()) return;
    await sleep(250);
  }
  bad("the dashboard did not come up within 15s; see .ares-dev/web.log");
  stop(1);
}

async function main() {
  const args = noDrill ? null : drillArgv();
  await startDashboard();
  console.log(`  dashboard: ${cyan(url)}   (log: .ares-dev/web.log)`);
  openBrowser();
  if (!args) {
    console.log("  Ctrl+C to stop.");
    return;
  }
  // Give the page a moment to load and take its "already on disk" snapshot;
  // anything written after that, it follows.
  await sleep(noOpen ? 0 : 3000);
  console.log(`  running: ${cyan(`ares ${args.join(" ")}`)}\n`);
  const drill = spawn(venvBin("ares"), args, {
    cwd: REPO, stdio: "inherit", env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
  children.push(drill);
  drill.on("exit", (code) => {
    if (stopping) return;
    console.log();
    const note = `drill finished (exit ${code}). The dashboard is still up at ${url} -- Ctrl+C to stop.`;
    if (code === 0) console.log(`  ${note}`);
    else todo(yellow(note));
  });
}

main().catch((err) => { bad(err.message); stop(1); });
