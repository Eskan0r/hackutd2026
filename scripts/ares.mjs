#!/usr/bin/env node
// Run the `ares` CLI from the venv on any OS -- terminal only, no dashboard.
// `npm run setup` also links this file as a global `ares` command (package.json
// "bin" + npm link), so `ares drill` works in any terminal without activating
// the venv. It runs in the folder you call it from, so relative paths you pass
// (ares fix lab/runs/kills/...) mean what you expect; the CLI itself resolves
// the lab, .env and lab/runs from the repo, never from the current folder.
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
  bad(`no .venv yet in ${REPO}: run \`npm run setup\` there first`);
  process.exit(1);
}

const ares = spawn(venvBin("ares"), process.argv.slice(2), {
  cwd: process.cwd(), stdio: "inherit", env: { ...process.env, PYTHONIOENCODING: "utf-8" },
});
ares.on("error", (err) => { bad(err.message); process.exit(2); });
ares.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
