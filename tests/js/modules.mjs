/* Every browser module loads, and every named import it asks for exists.
 *
 * Run by tests/test_playback.py. This is the cheap check that the page is not
 * simply blank: web/static has no build step, so a renamed export or a
 * duplicate declaration is not caught by anything until a browser tries to
 * load the module graph and gives up.
 *
 * `node --check` is NOT a substitute. It returned 0 on a scene.js that had
 * `const say` declared twice in one function -- a hard SyntaxError that this
 * check caught immediately, because it actually imports the module.
 */
globalThis.React = new Proxy({}, { get: (_, k) =>
  (k === "createElement" ? (() => null) : (() => undefined)) });

// What each module must export, because something else imports it by name.
const EXPECTED = {
  stage: ["standPoint", "randomSpot", "walkFor", "toolOf", "TOYS", "CASTLE", "CASTLE_ANIMS",
          "STAGE_W", "STAGE_H", "POYO_SIZE", "WALK_SPEED", "FALL_FROM", "GRAVITY",
          "IGNITE_MS", "ALARM", "ALARM_AT", "ALARM_LAMP_Y", "ALARM_RAISE_MS"],
  timeline: ["fold", "finish", "initial"],
  transport: ["useTransport"],
  sprite: ["html", "Sprite", "SPRITES", "usePoyoManifest"],
  effects: ["DustCanvas", "Puff"],
  director: ["demoScript", "demoHeader", "cuesFromView", "runHeader", "requestedRun"],
  controls: ["Controls"],
  terminal: ["Terminal", "parseDrill", "tokenize", "drillCommand", "line", "HELP"],
  shell: ["useShell"],
  scene: ["Scene"],
  login: ["Login", "readSession"],
};

let bad = 0;
for (const [name, names] of Object.entries(EXPECTED)) {
  let ns;
  try {
    ns = await import(`./ui/${name}.js`);
  } catch (e) {
    console.log(`FAIL ui/${name}.js does not load: ${e.message}`);
    bad++;
    continue;
  }
  const missing = names.filter((n) => !(n in ns));
  if (missing.length) {
    console.log(`FAIL ui/${name}.js is missing: ${missing.join(", ")}`);
    bad++;
  } else {
    console.log(`ok   ui/${name}.js`);
  }
}

/* Nothing may import a module that is not there, and app.js is the entry the
 * page actually loads, so it gets imported too. */
try {
  await import("./app.js");
  console.log("ok   app.js");
} catch (e) {
  // app.js calls ReactDOM.createRoot at import time; a missing DOM is fine,
  // a missing module is not.
  if (/Cannot find module|Failed to resolve|has already been declared|is not defined/.test(e.message)
      && !/ReactDOM|document/.test(e.message)) {
    console.log(`FAIL app.js: ${e.message}`);
    bad++;
  } else {
    console.log("ok   app.js (module graph resolved)");
  }
}

console.log(bad ? `\n${bad} PROBLEM(S)` : "\nmodule graph resolves; all imports satisfied");
process.exit(bad ? 1 : 0);
