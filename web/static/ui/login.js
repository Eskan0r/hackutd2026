/* Sign-in screen, with idle Poyo standing on the sign.
 *
 * Placeholder credentials until real auth exists. The password is compared
 * by SHA-256 so it never sits in the page source in the clear. This is a
 * gate for a demo, not security: anything client-side can be bypassed.
 */
import { html, Sprite, SPRITES, usePoyoManifest } from "/static/ui/sprite.js";

const { useState, useEffect, useRef, useCallback } = React;

const LOGIN_EMAIL = "ronakch8@gmail.com";
const LOGIN_PASSWORD_SHA256 = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8";
const SESSION_KEY = "ares.session";
const POYO_SCALE = 2;

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function readSession() {
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

function IdlePoyo({ manifest }) {
  const a = manifest.anims.idle;
  const [cw, ch] = manifest.cell;
  const [ax, ay] = manifest.anchor;
  return html`<${Sprite} src=${`${SPRITES}/poyo/idle.png`} w=${cw} h=${ch} frames=${a.frames}
    fps=${a.fps} x=${-ax} y=${-ay} scale=${POYO_SCALE} label="Poyo" />`;
}

export function Login({ onSignedIn }) {
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
        <div class="sign-poyo">${manifest && html`<${IdlePoyo} manifest=${manifest} />`}</div>
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
