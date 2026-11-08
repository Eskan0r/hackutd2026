// npm run setup -- one-step setup on Windows, macOS or Linux. Safe to re-run:
// it only creates what is missing. The cross-platform twin of ./setup.sh.
//
//   1. a Python 3.12+ venv in .venv
//   2. requirements + the `ares` command (pip install -e .), linked onto PATH
//      with `npm link` so a bare `ares drill` works in any terminal
//   3. .env from .env.example; ARES_ADMIN_TOKEN filled if empty; key check
//   4. Docker running?
//   (--test also runs the pytest suite)
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { appendFileSync, copyFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  IS_WIN, REPO, bad, cyan, hasVenv, ok, readEnvFile, todo, venvBin,
} from "./venv.mjs";

const ENV = join(REPO, ".env");
const run = (cmd, args, opts = {}) =>
  spawnSync(cmd, args, { cwd: REPO, stdio: "inherit", ...opts });
const quiet = (cmd, args) =>
  spawnSync(cmd, args, { cwd: REPO, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });

/** The first interpreter on this machine that is Python 3.12 or newer. */
function findPython() {
  const candidates = IS_WIN
    ? [["py", ["-3.13"]], ["py", ["-3.12"]], ["py", ["-3"]], ["python", []], ["python3", []]]
    : [["python3.13", []], ["python3.12", []], ["python3", []], ["python", []]];
  const check = "import sys; sys.exit(sys.version_info[:2] < (3, 12))";
  for (const [cmd, pre] of candidates) {
    const r = quiet(cmd, [...pre, "-c", check]);
    if (r.status === 0) return [cmd, pre];
  }
  return null;
}

function setupVenv() {
  if (!hasVenv()) {
    const py = findPython();
    if (!py) {
      bad("Python 3.12 or newer not found. Install it (python.org, or `brew install python@3.12`), then re-run.");
      process.exit(1);
    }
    const [cmd, pre] = py;
    if (run(cmd, [...pre, "-m", "venv", ".venv"]).status !== 0) {
      bad("could not create .venv");
      process.exit(1);
    }
  }
  const version = quiet(venvBin("python"), ["--version"]).stdout.trim();
  ok(`venv: ${version}`);

  const pip = (args) => run(venvBin("python"), ["-m", "pip", "install", "-q",
    "--disable-pip-version-check", ...args]).status === 0;
  if (!pip(["-r", "requirements.txt"]) || !pip(["-e", "."])) {
    bad("pip install failed (see the error above)");
    process.exit(1);
  }
  ok(`dependencies installed; the ares command is ${venvBin("ares")}`);
}

/** Put `ares` on PATH: npm link installs scripts/ares.mjs (package.json "bin")
 *  into npm's global bin, which is already on PATH wherever node is. Best
 *  effort -- a root-owned npm prefix just means using the venv path instead. */
function linkCommand() {
  const r = spawnSync("npm", ["link", "--silent", "--no-audit", "--no-fund"], {
    cwd: REPO, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], shell: IS_WIN,
  });
  const where = quiet(IS_WIN ? "where" : "which", ["ares"]);
  if (r.status === 0 && where.status === 0) {
    ok("`ares` is on your PATH: run `ares drill` from any terminal");
    return "ares";
  }
  const direct = IS_WIN ? ".venv\\Scripts\\ares" : "./.venv/bin/ares";
  todo(`could not put \`ares\` on PATH (npm link failed); use ${direct} instead`);
  return direct;
}

/** Make sure .env exists and has what the drill needs. Only empty values are
 *  ever filled, and only ARES_ADMIN_TOKEN (a random lab secret, like the VM
 *  bootstrap makes); the API keys are yours to paste. */
function setupEnv() {
  if (!existsSync(ENV)) {
    copyFileSync(join(REPO, ".env.example"), ENV);
    ok("created .env from .env.example");
  }
  let text = readFileSync(ENV, "utf8");
  const env = readEnvFile(ENV);
  if (!env.ARES_ADMIN_TOKEN) {
    const token = randomBytes(16).toString("hex");
    text = /^\s*ARES_ADMIN_TOKEN\s*=.*$/m.test(text)
      ? text.replace(/^\s*ARES_ADMIN_TOKEN\s*=.*$/m, `ARES_ADMIN_TOKEN=${token}`)
      : `${text.replace(/\s*$/, "\n")}ARES_ADMIN_TOKEN=${token}\n`;
    writeFileSync(ENV, text);
    ok("ARES_ADMIN_TOKEN generated in .env");
  }
  if (!("ARES_TARGET" in readEnvFile(ENV))) {
    appendFileSync(ENV, `${text.endsWith("\n") ? "" : "\n"}`
      + "# owner/repo that `npm run dev` drills (same as ares hunt --target)\nARES_TARGET=\n");
  }
  let ready = true;
  const now = readEnvFile(ENV);
  for (const key of ["NVIDIA_API_KEY", "GITHUB_TOKEN", "ARES_TARGET"]) {
    if (now[key]) ok(`${key} is set in .env`);
    else { todo(`${key} is empty in .env`); ready = false; }
  }
  return ready;
}

function checkDocker() {
  if (quiet("docker", ["info"]).status === 0) { ok("Docker is running"); return true; }
  todo("Docker is not running: start Docker Desktop (the lab runs in containers)");
  return false;
}

function runTests() {
  const r = quiet(venvBin("python"), ["-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"]);
  const last = (r.stdout || "").trim().split(/\r?\n/).pop();
  if (r.status === 0) ok(`tests: ${last}`);
  else todo(`tests: ${last}`);
}

console.log("Ares setup");
setupVenv();
const ares = linkCommand();
let ready = setupEnv();
ready = checkDocker() && ready;
if (process.argv.includes("--test")) runTests();

console.log();
console.log(ready ? "Ready. Next:" : "Almost there. Fill in the ! items above, then:");
console.log(`  1. Keys in .env (no quotes, no spaces around =):
       NVIDIA_API_KEY   build.nvidia.com (free)
       GITHUB_TOKEN     fine-grained, only your target repo; Contents + Pull requests read/write
       ARES_TARGET      the owner/repo to drill, e.g. you/sandbox-policy
  2. Once per target repo that has no policy yet:
       ${cyan(`${ares} setup-target <owner>/<repo>`)}
  3. Dashboard + drill, one command:
       ${cyan("npm run dev")}
     or just the drill, in this terminal:
       ${cyan(`${ares} hunt --target <owner>/<repo> --mode scripted`)}   recorded agent, no model calls
       ${cyan(`${ares} hunt --target <owner>/<repo>`)}                  live Nemotron (the default)`);
