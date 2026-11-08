// npm run trial -- one trial, CLI only. No dashboard, no browser.
//
//   npm run trial                       one live trial (`ares trial`)
//   npm run trial -- fetch_through      anything after -- goes to `ares trial`
//
// A dashboard that is already open (`npm run dashboard`) picks the run up on
// its own: follow mode looks for a new run every two seconds.
import { spawn } from "node:child_process";
import { REPO, bad, hasVenv, venvBin } from "./venv.mjs";

if (!hasVenv()) {
  bad("no .venv yet: run `npm run setup` first");
  process.exit(1);
}

const trial = spawn(venvBin("ares"), ["trial", ...process.argv.slice(2)], {
  cwd: REPO, stdio: "inherit", env: { ...process.env, PYTHONIOENCODING: "utf-8" },
});
trial.on("error", (err) => { bad(err.message); process.exit(2); });
trial.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
