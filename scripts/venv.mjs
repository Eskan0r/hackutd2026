// Shared by scripts/setup.mjs and scripts/dev.mjs (npm run setup / dev).
//
// Node is only the task runner here: the dashboard has no build step and
// installs nothing from npm (CLAUDE.md). These helpers exist because the venv
// lays out differently per OS -- .venv/Scripts/python.exe on Windows,
// .venv/bin/python elsewhere -- which a one-line npm script cannot paper over.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const IS_WIN = process.platform === "win32";
const BIN = join(REPO, ".venv", IS_WIN ? "Scripts" : "bin");

/** Path to an executable inside the venv (`python`, `ares`, ...). */
export function venvBin(name) {
  return join(BIN, IS_WIN ? `${name}.exe` : name);
}

export const hasVenv = () => existsSync(venvBin("python"));

/** KEY=value pairs from the repo-root .env; {} when there is none. Values are
 *  never printed by the callers -- only whether they are set. */
export function readEnvFile(path = join(REPO, ".env")) {
  if (!existsSync(path)) return {};
  const out = {};
  for (const raw of readFileSync(path, "utf8").split(/\r?\n/)) {
    const m = /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/.exec(raw);
    if (!m) continue;
    out[m[1]] = m[2].trim().replace(/^(['"])(.*)\1$/, "$2");
  }
  return out;
}

const color = (code) => (text) => (process.stdout.isTTY ? `\x1b[${code}m${text}\x1b[0m` : text);
export const green = color(32);
export const red = color(31);
export const yellow = color(33);
export const cyan = color(36);
export const ok = (msg) => console.log(`  ${green("✓")} ${msg}`);
export const bad = (msg) => console.log(`  ${red("✗")} ${msg}`);
export const todo = (msg) => console.log(`  ${yellow("!")} ${msg}`);
