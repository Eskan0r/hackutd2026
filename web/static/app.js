/* Ares -- the sandbox view. React, no build step.
 *
 * React and htm are vendored under /static/vendor, so these modules run in the
 * browser as written: no npm, no bundler, no CDN.
 *
 *   ui/login.js     sign-in, with idle Poyo on the sign
 *   ui/stage.js     where everything is on the sand: pure layout, no React
 *   ui/director.js  turns a demo script or a recorded run into beats (cues)
 *   ui/timeline.js  folds cues into a scene -- what makes the run seekable
 *   ui/transport.js play, pause, step: the cursor is the only state
 *   ui/controls.js  the transport bar
 *   ui/scene.js     the sandbox: props, Poyo acting out the cue, bubble
 *   ui/terminal.js  the drill console: a prompt you can type into
 *   ui/shell.js     what those commands do (the only part that POSTs)
 *   ui/sprite.js    sprite-strip playback shared by all of them
 *
 * Login is client-side only. The viewer server is GET-only and
 * tests/test_web.py pins that; `ares drill` from the console needs the
 * separate operator app (web/operator.py), and the console says which one it
 * is talking to.
 */
import { html } from "/static/ui/sprite.js";
import { Login, readSession } from "/static/ui/login.js";
import { Scene } from "/static/ui/scene.js";

const { useState } = React;

function App() {
  const [signedIn, setSignedIn] = useState(readSession);
  return signedIn
    ? html`<${Scene} />`
    : html`<${Login} onSignedIn=${() => setSignedIn(true)} />`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
