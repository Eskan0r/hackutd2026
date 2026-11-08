/* Ares -- the sandbox view. React, no build step.
 *
 * React and htm are vendored under /static/vendor, so this module runs in the
 * browser as written: no npm, no bundler, no CDN.
 *
 * Two screens: a login, then the sandbox scene. The scene is visual only for
 * now -- nothing in it is clickable and nothing reads drill data yet. Every
 * sprite is baked art from web/static/sprites (see scripts/make_scene_sprites.py
 * and scripts/bake_poyo.py); this file only places and plays them.
 *
 * The page never acts on anything: the login is client-side only and the
 * server stays GET-only (tests/test_web.py pins that).
 */
import htm from "/static/vendor/htm.js";

const { useState, useEffect, useRef, useCallback } = React;
const html = htm.bind(React.createElement);

// ------------------------------------------------------------------ stage

/* Native resolution of the scene. Everything below is in these pixels and
 * scaled by one whole-number factor, so every sprite pixel stays square. */
const STAGE_W = 512;
const STAGE_H = 288;
const SPRITES = "/static/sprites";

/* Props on the sand, top-left corners in stage pixels. One toy per agent
 * tool; the castle is the boundary that burns on a breakout. */
const CASTLE = { src: `${SPRITES}/castle-idle.png`, w: 64, h: 84, frames: 4, fps: 4, x: 360, y: 70 };
const TOYS = [
  { tool: "http_get",       src: "toy-get",     x: 96,  y: 70 },
  { tool: "http_post",      src: "toy-post",    x: 176, y: 58 },
  { tool: "read_file",      src: "toy-read",    x: 88,  y: 182 },
  { tool: "list_dir",       src: "toy-list",    x: 150, y: 214 },
  { tool: "run_cmd",        src: "toy-run",     x: 300, y: 210 },
  { tool: "report_blocked", src: "toy-blocked", x: 432, y: 190 },
];
const POYO_FEET = { x: 250, y: 185 };

/** Largest whole-number scale at which the stage fits the window (min 1). */
function useStageScale() {
  const fit = () =>
    Math.max(1, Math.floor(Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H)));
  const [scale, setScale] = useState(fit);
  useEffect(() => {
    const onResize = () => setScale(fit());
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return scale;
}

/** poyo.json: cell size, foot anchor and per-animation frame counts. */
function usePoyoManifest() {
  const [manifest, setManifest] = useState(null);
  useEffect(() => {
    let live = true;
    fetch(`${SPRITES}/poyo/poyo.json`)
      .then((r) => r.json())
      .then((m) => { if (live) setManifest(m); })
      .catch(() => { /* no Poyo is better than a broken page */ });
    return () => { live = false; };
  }, []);
  return manifest;
}

/**
 * One animated sprite. The strip is an <img> inside a box one frame wide; a
 * stepped CSS transform slides it a frame at a time (compositor-only motion).
 * `delay` desynchronises props that share a loop so they don't tick in unison.
 */
function Sprite({ src, w, h, frames, fps, x, y, scale, delay = 0, z, label }) {
  const style = {
    left: `${x * scale}px`,
    top: `${y * scale}px`,
    width: `${w * scale}px`,
    height: `${h * scale}px`,
    zIndex: z ?? Math.round(y + h),
  };
  const strip = {
    width: `${w * frames * scale}px`,
    height: `${h * scale}px`,
    animationDuration: `${frames / fps}s`,
    animationTimingFunction: `steps(${frames})`,
    animationDelay: `${-delay}s`,
    animationPlayState: frames > 1 ? "running" : "paused",
  };
  return html`
    <div class="sprite" style=${style} role=${label ? "img" : undefined} aria-label=${label}>
      <img src=${src} alt="" draggable="false" style=${strip} />
    </div>`;
}

/** Poyo, playing one baked animation from poyo.json, feet on `feet`. */
function Poyo({ manifest, anim = "idle", feet, scale }) {
  const a = manifest.anims[anim];
  const [cw, ch] = manifest.cell;
  const [ax, ay] = manifest.anchor;
  return html`<${Sprite}
    src=${`${SPRITES}/poyo/${anim}.png`} w=${cw} h=${ch} frames=${a.frames} fps=${a.fps}
    x=${feet.x - ax} y=${feet.y - ay} z=${feet.y} scale=${scale} label="Poyo, the agent" />`;
}

function Scene() {
  const scale = useStageScale();
  const manifest = usePoyoManifest();
  const stage = { width: `${STAGE_W * scale}px`, height: `${STAGE_H * scale}px` };
  return html`
    <main class="scene">
      <div class="stage" style=${stage} role="img" aria-label="The sandbox">
        <img class="ground" src=${`${SPRITES}/sandbox.png`} alt="" draggable="false"
             width=${STAGE_W * scale} height=${STAGE_H * scale} />
        <${Sprite} ...${CASTLE} scale=${scale} label="Sandcastle: the boundary" />
        ${TOYS.map((t, i) => html`
          <${Sprite} key=${t.tool} src=${`${SPRITES}/${t.src}.png`} w=${32} h=${32}
            frames=${4} fps=${3} x=${t.x} y=${t.y} scale=${scale}
            delay=${i * 0.37} label=${`Tool: ${t.tool}`} />`)}
        ${manifest && html`<${Poyo} manifest=${manifest} feet=${POYO_FEET} scale=${scale} />`}
      </div>
    </main>`;
}

// ------------------------------------------------------------------ login

/* Placeholder credentials until real auth exists. The password is compared
 * by SHA-256 so it never sits in the page source in the clear. This is a
 * gate for a demo, not security: anything client-side can be bypassed. */
const LOGIN_EMAIL = "ronakch8@gmail.com";
const LOGIN_PASSWORD_SHA256 = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8";
const SESSION_KEY = "ares.session";

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function readSession() {
  try { return sessionStorage.getItem(SESSION_KEY) === "1"; } catch { return false; }
}

function writeSession() {
  try { sessionStorage.setItem(SESSION_KEY, "1"); } catch { /* private mode: stay in memory */ }
}

const IconPerson = () => html`
  <svg viewBox="0 0 11 11" class="icon" aria-hidden="true" shape-rendering="crispEdges">
    <rect x="3" y="0" width="5" height="5" fill="var(--ink)" /><rect x="4" y="1" width="3" height="3" fill="var(--fur)" />
    <rect x="1" y="6" width="9" height="5" fill="var(--ink)" /><rect x="2" y="7" width="7" height="4" fill="var(--hoodie)" />
  </svg>`;

const IconKey = () => html`
  <svg viewBox="0 0 11 11" class="icon" aria-hidden="true" shape-rendering="crispEdges">
    <rect x="0" y="2" width="5" height="5" fill="var(--ink)" /><rect x="1" y="3" width="3" height="3" fill="var(--clasp)" />
    <rect x="2" y="4" width="1" height="1" fill="var(--ink)" />
    <rect x="5" y="4" width="6" height="2" fill="var(--ink)" /><rect x="8" y="6" width="1" height="2" fill="var(--ink)" />
    <rect x="10" y="6" width="1" height="2" fill="var(--ink)" />
  </svg>`;

const IconGo = () => html`
  <svg viewBox="0 0 11 11" class="icon icon-go" aria-hidden="true" shape-rendering="crispEdges">
    <rect x="0" y="4" width="6" height="3" fill="currentColor" />
    <rect x="5" y="1" width="2" height="9" fill="currentColor" /><rect x="7" y="2" width="1" height="7" fill="currentColor" />
    <rect x="8" y="3" width="1" height="5" fill="currentColor" /><rect x="9" y="4" width="1" height="3" fill="currentColor" />
    <rect x="10" y="5" width="1" height="1" fill="currentColor" />
  </svg>`;

function Login({ onSignedIn }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rejected, setRejected] = useState(0);   // bump to replay the shake
  const [busy, setBusy] = useState(false);
  const manifest = usePoyoManifest();
  const emailRef = useRef(null);

  useEffect(() => { emailRef.current?.focus(); }, [rejected]);

  const submit = useCallback(async (ev) => {
    ev.preventDefault();
    if (busy) return;
    setBusy(true);
    const ok = email.trim().toLowerCase() === LOGIN_EMAIL &&
      (await sha256Hex(password)) === LOGIN_PASSWORD_SHA256;
    setBusy(false);
    if (ok) {
      writeSession();
      onSignedIn();
    } else {
      setRejected((n) => n + 1);
      setPassword("");
    }
  }, [email, password, busy, onSignedIn]);

  return html`
    <main class="login">
      <form class=${`sign ${rejected ? "sign-no" : ""}`} key=${rejected} onSubmit=${submit}
            aria-label="Sign in">
        <div class="sign-poyo">
          ${manifest && html`<${Poyo} manifest=${manifest}
              feet=${{ x: manifest.anchor[0], y: manifest.anchor[1] }} scale=${2} />`}
        </div>
        <h1 class="sign-title">Sign in to Ares</h1>
        <label class="row">
          <span class="label">Email</span>
          <span class="field">
            <${IconPerson} />
            <input ref=${emailRef} type="email" autocomplete="username"
                   value=${email} onInput=${(e) => setEmail(e.target.value)} required />
          </span>
        </label>
        <label class="row">
          <span class="label">Password</span>
          <span class="field">
            <${IconKey} />
            <input type="password" autocomplete="current-password"
                   value=${password} onInput=${(e) => setPassword(e.target.value)} required />
          </span>
        </label>
        ${rejected > 0 && html`<p class="error" role="alert">Wrong email or password.</p>`}
        <button class="go" type="submit" disabled=${busy}>
          <span>Sign in</span><${IconGo} />
        </button>
      </form>
    </main>`;
}

// ------------------------------------------------------------------ app

function App() {
  const [signedIn, setSignedIn] = useState(readSession);
  return signedIn
    ? html`<${Scene} />`
    : html`<${Login} onSignedIn=${() => setSignedIn(true)} />`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
