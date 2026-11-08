// Run the `ares` CLI from the venv on any OS -- terminal only, no dashboard.
//
//   npm run trial                       one live trial            (ares trial)
//   npm run trial -- fetch_through      replay a recording, no API key needed
//   npm run trials                      10 live trials in a row   (ares drill --mode live --n 10)
//   npm run trials -- --policy after    anything after -- is passed on to ares
//
// A dashboard that is already open (`npm run dashboard`) picks each run up on
// its own: follow mode looks for a new run every two seconds.
import { spawn } from "node:child_process";
import { REPO, bad, hasVenv, venvBin } from "./venv.mjs";

if (!hasVenv()) {
  bad("no .venv yet: run `npm run setup` first");
  process.exit(1);
}

const ares = spawn(venvBin("ares"), process.argv.slice(2), {
  cwd: REPO, stdio: "inherit", env: { ...process.env, PYTHONIOENCODING: "utf-8" },
});
ares.on("error", (err) => { bad(err.message); process.exit(2); });
ares.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
