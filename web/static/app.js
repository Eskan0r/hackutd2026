/* Ares -- the sandbox view. React, no build step.
 *
 * React and htm are vendored under /static/vendor, so these modules run in the
 * browser as written: no npm, no bundler, no CDN.
 *
 *   ui/login.js     sign-in, with idle Poyo on the sign
 *   ui/scene.js     the sandbox: props, Poyo acting out a run, speech bubble
 *   ui/director.js  turns a demo script or a recorded run into Poyo's beats
 *   ui/logs.js      the command-prompt style log console
 *   ui/sprite.js    sprite-strip playback shared by all of them
 *
 * The page never acts on anything: login is client-side only and the server
 * stays GET-only (tests/test_web.py pins that).
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
