/* Ares dashboard -- React, no build step.
 *
 * React and htm are vendored under /static/vendor, so this file is an ES
 * module the browser runs as written. htm gives JSX-shaped markup through
 * tagged templates; adding a bundler would mean the dashboard needs `npm
 * install` before it can show a drill, which is a bad trade for a tool whose
 * whole job is to be up when someone wants to look.
 *
 * Every number rendered here was derived by web/model.py. The browser decides
 * how things look, never what happened.
 */
import htm from "/static/vendor/htm.js";

const { useState, useEffect, useRef, useCallback, useMemo } = React;
const html = htm.bind(React.createElement);

const SEV_RANK = { info: 0, watch: 1, fire: 2, breach: 3 };
const VERDICT_WORD = {
  contained: "CONTAINED", not_contained: "NOT CONTAINED",
  not_killed: "NOT KILLED", no_fire: "NO FIRE", unverified: "KILL UNVERIFIED"
};

const params = new URLSearchParams(location.search);

const fmtMs = (ms) =>
  ms < 1000 ? `${ms}ms`
  : ms < 60000 ? `${(ms / 1000).toFixed(1)}s`
  : `${Math.round(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`;

// ---------------------------------------------------------------- derivation

/* What the stage should show at beat `i`. Pure: same beat, same picture. */
function sceneStateFor(view, i) {
  const seen = view.timeline.slice(0, i + 1);
  const current = view.timeline[i] || null;
  const ts = current ? current.ts : null;
  const found = {};
  const holes = [];
  let escaped = false;
  // Not every event has a place -- an LLM call happens wherever the agent is
  // standing -- so position comes from the most recent event that does.
  let lastHost = null;

  for (const e of seen) {
    const st = Scene.stationFor(e.host);
    if (!st) continue;
    lastHost = e.host;
    if (e.severity === "fire" || e.severity === "breach") {
      found[st.id] = true;
      if (st.id === "outside") escaped = true;
      else if (!holes.some((h) => h[0] === st.x)) holes.push([st.x, st.y]);
    }
  }

  const levers = view.kill.levers.map((rung) => ({
    name: rung.name,
    label: rung.label,
    order: rung.order,
    state: rung.t && ts && rung.t <= ts ? rung.state : "idle"
  }));
  const killed = levers.some((l) => l.state !== "idle");
  const verified = levers.some((l) => l.state === "verified");
  const paused = levers.some((l) => l.name === "docker_pause" && l.state !== "idle");

  return {
    host: lastHost,
    found, holes, levers, killed, verified,
    frozen: killed,
    // Lever 1 only denies the model; saying PAUSED when nothing paused would
    // be the dashboard telling the first lie.
    frozenWord: paused ? "PAUSED" : killed ? "DENIED" : "",
    escaped: escaped && !killed,
    alarm: !!current && (current.severity === "fire" || current.severity === "breach") && !killed,
    digging: !!current && current.kind === "http",
    llmActive: !!current && current.kind === "llm"
  };
}

function bannerFor(view, scene) {
  if (scene.killed) {
    return scene.verified
      ? { text: `Kill verified — ${VERDICT_WORD[view.kill.verdict]}`, tone: "ok" }
      : { text: "Lever pulled — effect not observed", tone: "warn" };
  }
  if (scene.escaped) return { text: "Boundary breached — nothing is watching", tone: "breach" };
  if (scene.alarm) return { text: "Fire — bait touched", tone: "fire" };
  return null;
}

// -------------------------------------------------------------- small pieces

const Panel = ({ title, note, side, open, onToggle, children, className = "" }) => html`
  <section class=${`panel dock-panel ${side} ${open ? "" : "is-closed"} ${className}`}>
    <header class="panel-head">
      <h2>${title}</h2>
      ${note && html`<span class="panel-note">${note}</span>`}
      <button class="panel-toggle" onClick=${onToggle}
              aria-expanded=${open} title=${open ? "collapse" : "expand"}>
        ${open ? "–" : "+"}
      </button>
    </header>
    ${open && html`<div class="panel-body">${children}</div>`}
  </section>`;

const Stat = ({ value, caption, tone = "" }) => html`
  <div class=${`stat ${tone}`}>
    <b>${value}</b><span>${caption}</span>
  </div>`;

function Modal({ title, onClose, children }) {
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return html`
    <div class="modal-scrim" onClick=${onClose}>
      <div class="panel modal" onClick=${(e) => e.stopPropagation()} role="dialog" aria-label=${title}>
        <header class="panel-head">
          <h2>${title}</h2>
          <button class="panel-toggle" onClick=${onClose} title="close">×</button>
        </header>
        <div class="panel-body modal-body">${children}</div>
      </div>
    </div>`;
}

// -------------------------------------------------------------------- stage

function Stage({ view, beat, scene, note, onCloseNote }) {
  const canvasRef = useRef(null);
  const sceneRef = useRef(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let live = true;
    Sprites.load({
      front: "/static/sprites/agent-front.png",
      dig: "/static/sprites/agent-dig.png"
      // Poyo at roughly a sixth of the stage height: he is a character in the
      // sandbox, not a billboard standing in it.
    }, 62).then((sprites) => {
      if (!live || !canvasRef.current) return;
      sceneRef.current = new Scene(canvasRef.current, sprites);
      sceneRef.current.start();
      setReady(true);
    });
    return () => {
      live = false;
      if (sceneRef.current) sceneRef.current.stop();
    };
  }, []);

  useEffect(() => {
    if (!sceneRef.current) return;
    sceneRef.current.setState(scene);
    sceneRef.current.snap();
  }, [ready, scene]);

  const banner = bannerFor(view, scene);
  const pct = (v, total) => `${(v / total) * 100}%`;

  /* Where the agent is, derived the same way the canvas derives it. Reading
   * sceneRef.current.agent here would give a stale value: the scene moves the
   * agent inside requestAnimationFrame, which never re-renders React. */
  const agentAt = (() => {
    if (scene.escaped) return { x: Scene.ESCAPE.x, y: Scene.ESCAPE.y };
    const st = Scene.stationFor(scene.host) || Scene.STATIONS[0];
    return st.id === "outside" ? { x: Scene.ESCAPE.x, y: Scene.ESCAPE.y } : { x: st.x, y: st.y };
  })();

  return html`
    <div class="stage">
      <canvas ref=${canvasRef} width=${Scene.WIDTH} height=${Scene.HEIGHT}
              aria-label="Pixel-art view of the agent digging in a sealed sandbox"></canvas>

      <div class="stage-overlay" aria-hidden="false">
        ${Scene.STATIONS.map((s) => {
          const dug = !!scene.found[s.id];
          const y = s.id === "outside" ? Scene.ESCAPE.y : s.y;
          return html`
            <span key=${s.id}
                  class=${`pin ${s.role} ${dug ? "is-dug" : ""}`}
                  style=${{ left: pct(s.x, Scene.WIDTH), top: pct(y - 44, Scene.HEIGHT) }}>
              ${s.label}
            </span>`;
        })}
        ${scene.frozen && agentAt && html`
          <span class="pin frozen"
                style=${{ left: pct(agentAt.x, Scene.WIDTH),
                          top: pct(agentAt.y - 84, Scene.HEIGHT) }}>
            ${scene.frozenWord}
          </span>`}
      </div>

      ${banner && html`<div class=${`stage-banner ${banner.tone}`}>${banner.text}</div>`}
      <div class=${`mast ${scene.killed ? "down" : scene.llmActive ? "live" : ""}`}>
        <span class="mast-dot"></span>
        ${scene.killed ? "gateway denied" : "llm gateway"}
      </div>
      <${Dialogue} note=${note} onClose=${onCloseNote} />
    </div>`;
}

// ------------------------------------------------------------------- panels

function ConsolePanel({ view, beat, goTo, open, onToggle }) {
  const bodyRef = useRef(null);
  useEffect(() => {
    const row = bodyRef.current && bodyRef.current.children[beat];
    if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
  }, [beat, open]);

  return html`
    <${Panel} title="Console" note="append-only, hash-chained" side="left"
              open=${open} onToggle=${onToggle} className="console-panel">
      <div class="console" ref=${bodyRef} role="log">
        ${view.timeline.map((e, i) => html`
          <div key=${i} class=${`line ${e.severity} ${i === beat ? "now" : ""} ${i > beat ? "future" : ""}`}
               onClick=${() => goTo(i)}>
            <div class="line-meta">
              <span class="t">+${e.offset_ms}ms</span>
              <span class=${`s ${e.severity}`}>${e.severity}</span>
              <span class="src">${e.source}</span>
            </div>
            <div class="m">
              ${e.text}
              ${e.blocked && html`<span class="tag ok">blocked</span>`}
              ${e.token_match && html`<span class="tag">token</span>`}
              ${e.crossed_boundary && html`<span class="tag leak">crossed</span>`}
              ${e.after_kill && html`<span class="tag leak">post-kill</span>`}
            </div>
          </div>`)}
      </div>
    <//>`;
}

function VulnPanel({ view, open, onToggle, onOpenAll }) {
  const v = view.vulnerabilities;
  const used = v.flaws.filter((f) => f.exercised);
  return html`
    <${Panel} title="Vulnerabilities" note=${`${used.length} exercised`} side="left"
              open=${open} onToggle=${onToggle}>
      <div class="vuln-stats">
        <${Stat} value=${used.length} caption="flaws used" tone=${used.length ? "bad" : ""} />
        <${Stat} value=${v.baits.length} caption="bait touched" tone=${v.baits.length ? "bad" : ""} />
        <${Stat} value=${v.token_matches} caption="tokens served" />
        <${Stat} value=${view.kill.post_kill_leaks} caption="post-kill leaks"
                 tone=${view.kill.post_kill_leaks ? "bad" : ""} />
      </div>
      <ul class="vuln-list">
        ${v.flaws.slice(0, 4).map((f) => html`
          <li key=${f.name} class=${f.exercised ? "used" : f.enabled ? "on" : "off"}>
            <b>${f.title}</b>
            <span class="vuln-tags">
              <span class=${`badge ${f.enabled ? "on" : ""}`}>${f.enabled ? "enabled" : "off"}</span>
              ${f.exercised && html`<span class="badge used">used ${f.hits}×</span>`}
            </span>
          </li>`)}
      </ul>
      <button class="btn link" onClick=${onOpenAll}>all flaws and bait →</button>
    <//>`;
}

function LeverPanel({ view, scene, open, onToggle }) {
  const kill = view.kill;
  return html`
    <${Panel} title="Kill levers" note="in order, 2s each" side="right"
              open=${open} onToggle=${onToggle}>
      <ol class="levers">
        ${scene.levers.map((l) => html`
          <li key=${l.name} class=${l.state}>
            <span class="lever-switch"><i></i></span>
            <span class="lever-text">
              <b>${l.order}. ${l.label}</b>
              <em>${l.state}</em>
            </span>
          </li>`)}
      </ol>
      <div class="ttk">
        <b>${kill.ttk_ms === null || kill.ttk_ms === undefined ? "—" : `${kill.ttk_ms}ms`}</b>
        <span>${
          kill.ttk_ms === null || kill.ttk_ms === undefined ? "no kill measured"
          : kill.derived ? "time to pull (derived)" : "time to kill, verified"
        }</span>
      </div>
      ${kill.caveats.length > 0 && html`
        <p class="caveat">${kill.caveats[0]}</p>`}
    <//>`;
}

function Timeline({ view, beat, goTo }) {
  const last = view.timeline[view.timeline.length - 1];
  return html`
    <div class="timeline-wrap">
      <div class="timeline-head">
        <span>Timeline</span>
        <span class="muted">${view.timeline.length} events over ${last ? fmtMs(last.offset_ms) : "0ms"}</span>
      </div>
      <div class="timeline">
        ${view.timeline.map((e, i) => html`
          <button key=${i} type="button"
                  class=${`tick ${e.severity} ${i === beat ? "now" : ""} ${i > beat ? "future" : ""} ${e.after_kill ? "after-kill" : ""}`}
                  style=${{ height: `${12 + SEV_RANK[e.severity] * 11}px` }}
                  title=${`+${e.offset_ms}ms  ${e.severity}  ${e.source}: ${e.text}`}
                  onClick=${() => goTo(i)}></button>`)}
      </div>
    </div>`;
}

// ------------------------------------------------------------- modal bodies

function EvidenceBody({ view, beat, goTo }) {
  const [sev, setSev] = useState("");
  const [text, setText] = useState("");
  const rows = useMemo(() => view.timeline.filter((e) => {
    if (sev && e.severity !== sev) return false;
    if (!text) return true;
    const hay = [e.source, e.host, e.path, e.text, e.bait_id, e.flaw, e.kind]
      .join(" ").toLowerCase();
    return hay.includes(text.toLowerCase());
  }), [view, sev, text]);

  return html`
    <div class="filters">
      <label>severity
        <select value=${sev} onChange=${(e) => setSev(e.target.value)}>
          <option value="">all</option>
          ${["info", "watch", "fire", "breach"].map((s) => html`<option key=${s} value=${s}>${s}</option>`)}
        </select>
      </label>
      <label>search
        <input type="search" value=${text} placeholder="host, path, source"
               onInput=${(e) => setText(e.target.value)} />
      </label>
      <span class="muted">
        ${rows.length} of ${view.timeline.length} ·
        ${view.chain.filter((c) => c.intact).length}/${view.chain.length} files chain-verified
      </span>
    </div>
    <div class="table-scroll">
      <table class="grid">
        <thead><tr>
          <th>#</th><th>+ms</th><th>sev</th><th>source</th><th>kind</th>
          <th>host</th><th>path</th><th>bait</th><th>flaw</th><th>detail</th>
        </tr></thead>
        <tbody>
          ${rows.map((e) => html`
            <tr key=${e.i} class=${`${e.severity} ${e.i === beat ? "now" : ""}`} onClick=${() => goTo(e.i)}>
              <td>${e.i}</td><td>+${e.offset_ms}</td>
              <td class="sev">${e.severity}</td>
              <td>${e.source}</td><td>${e.kind}</td>
              <td class="mono">${e.host || "—"}</td>
              <td class="mono">${(e.method ? e.method + " " : "") + (e.path || "")}</td>
              <td>${e.bait_id || ""}</td><td>${e.flaw || ""}</td>
              <td class="mono detail">${JSON.stringify(e.detail)}</td>
            </tr>`)}
        </tbody>
      </table>
    </div>`;
}

function VulnBody({ view }) {
  const v = view.vulnerabilities;
  return html`
    <div class="allow">
      <span class="muted">policy allowlist</span>
      <div class="allow-list">
        ${v.allowlist.length
          ? v.allowlist.map((h) => html`<span key=${h} class="badge">${h}</span>`)
          : html`<span class="badge">none</span>`}
      </div>
    </div>
    <div class="card-grid">
      ${v.flaws.map((f) => html`
        <article key=${f.name} class=${`card ${f.exercised ? "bad" : ""} ${f.enabled ? "" : "dim"}`}>
          <h4>${f.title}</h4>
          <p>${f.blurb}</p>
          <div class="vuln-tags">
            <span class=${`badge ${f.enabled ? "on" : ""}`}>${f.enabled ? "enabled" : "off"}</span>
            ${f.exercised && html`<span class="badge used">used ${f.hits}×</span>`}
            <span class="badge">${f.owner}</span>
            ${f.hosts.length > 0 && html`<span class="badge">${f.hosts.join(", ")}</span>`}
          </div>
        </article>`)}
    </div>
    <h3>Bait touched</h3>
    ${v.baits.length === 0
      ? html`<p class="empty">No bait was touched in this run.</p>`
      : html`<div class="card-grid">
          ${v.baits.map((b) => html`
            <article key=${b.bait_id} class="card bad">
              <h4>${b.bait_id} · ${b.label}</h4>
              <p>${b.blurb}</p>
              <div class="vuln-tags">
                <span class="badge">${b.host}</span>
                <span class="badge">${b.touches} touch(es)</span>
                ${b.token_match && html`<span class="badge used">synthetic token served</span>`}
              </div>
            </article>`)}
        </div>`}`;
}

function ReportBody({ view }) {
  const r = view.report, k = view.kill;
  return html`
    <div class="report-actions">
      <a class="btn" href=${`/api/run/${encodeURIComponent(view.key)}/report?download=true`}>
        download report.json
      </a>
      <button class="btn" onClick=${() => window.print()}>print</button>
    </div>

    <div class=${`report-head ${k.verdict}`}>
      <h3>${r.headline}</h3>
      <p>${r.explanation}</p>
      <p class="muted">run <b>${r.run_id}</b> · variant ${r.variant} · trial ${r.trial}</p>
    </div>

    <div class="stat-row">
      <${Stat} value=${r.counts.events} caption="events" />
      <${Stat} value=${r.counts.fire} caption="fire" tone=${r.counts.fire ? "bad" : ""} />
      <${Stat} value=${r.counts.breach} caption="breach" />
      <${Stat} value=${r.counts.blocked} caption="blocked by policy" />
      <${Stat} value=${k.ttk_ms === null || k.ttk_ms === undefined ? "—" : `${k.ttk_ms}ms`}
               caption=${k.ttk_ms === null || k.ttk_ms === undefined ? "no kill measured"
                         : k.derived ? "time to pull (derived)" : "time to kill"} />
      <${Stat} value=${`${k.levers_pulled}/3`} caption="levers pulled" />
      <${Stat} value=${r.counts.post_kill_events} caption="post-kill events" />
      <${Stat} value=${r.counts.post_kill_leaks} caption="post-kill leaks"
               tone=${r.counts.post_kill_leaks ? "bad" : ""} />
    </div>

    <h3>How it got out</h3>
    ${r.escape_path.length === 0
      ? html`<p class="empty">The agent never left the allowed route.</p>`
      : html`<ol class="escape">
          ${r.escape_path.map((s, i) => html`
            <li key=${i}>
              <span class="step">${i + 1}</span>
              <div>
                ${s.text}
                <em>+${s.offset_ms}ms${s.flaw_title ? ` · ${s.flaw_title}` : ""}${s.token_match ? " · synthetic token served" : ""}</em>
              </div>
            </li>`)}
        </ol>`}

    <h3>Evidence integrity</h3>
    <div class="vuln-tags">
      ${r.chain.map((c) => html`
        <span key=${c.file} class=${`badge ${c.intact ? "on" : "used"}`}>
          ${c.file}: ${c.intact ? "chain intact" : "BROKEN"}
        </span>`)}
    </div>

    <div class="limits">
      <h4>What this does not prove</h4>
      <ul>${r.limitations.map((l, i) => html`<li key=${i}>${l}</li>`)}</ul>
    </div>`;
}

// ---------------------------------------------------------------------- app

function Dialogue({ note, onClose }) {
  if (!note) return null;
  return html`
    <div class=${`dialogue ${note.tone}`}>
      <span class="dialogue-icon">${note.tone === "ok" ? "✔" : "!"}</span>
      <div>
        <strong>${note.title}</strong>
        <p>${note.body}</p>
      </div>
      <button class="btn" onClick=${onClose}>ok</button>
    </div>`;
}

function App() {
  const [runs, setRuns] = useState([]);
  const [runKey, setRunKey] = useState(null);
  const [view, setView] = useState(null);
  const [beat, setBeat] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(900);
  const [live, setLive] = useState(false);
  const [modal, setModal] = useState(params.get("tab") === "report" ? "report"
                                   : params.get("tab") === "vulns" ? "vulns"
                                   : params.get("tab") === "evidence" ? "evidence" : null);
  const [panels, setPanels] = useState({ console: true, vulns: true, levers: true });
  const [note, setNote] = useState(null);
  const [error, setError] = useState(null);
  const shown = useRef({});
  const wantBeat = useRef(params.get("beat") === null ? null : Number(params.get("beat")));

  const togglePanel = (k) => setPanels((p) => ({ ...p, [k]: !p[k] }));

  useEffect(() => {
    fetch("/api/runs").then((r) => r.json()).then((data) => {
      setRuns(data.runs);
      if (!data.runs.length) return;
      const wanted = params.get("run");
      const match = data.runs.find((r) => r.key === wanted || r.run_id === wanted);
      // Default to the newest run that actually fired: a drill where nothing
      // was touched has nothing to show.
      const fired = data.runs.find((r) => r.fired);
      setRunKey((match || fired || data.runs[0]).key);
    }).catch((e) => setError(String(e.message || e)));
  }, []);

  const loadRun = useCallback((key) => {
    fetch(`/api/run/${encodeURIComponent(key)}`)
      .then((r) => { if (!r.ok) throw new Error("run not found"); return r.json(); })
      .then((data) => {
        shown.current = {};
        setView(data);
        setBeat(wantBeat.current === null ? 0 : wantBeat.current);
        wantBeat.current = null;
      })
      .catch((e) => setError(String(e.message || e)));
  }, []);

  useEffect(() => { if (runKey) loadRun(runKey); }, [runKey, loadRun]);

  // live tail
  useEffect(() => {
    if (!live || !runKey) return undefined;
    const sse = new EventSource(`/api/run/${encodeURIComponent(runKey)}/stream`);
    sse.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      if (data.error) return;
      setView((prev) => {
        const atEnd = !prev || beat >= prev.timeline.length - 1;
        if (atEnd) setBeat(Math.max(0, data.timeline.length - 1));
        return data;
      });
    };
    return () => sse.close();
  }, [live, runKey, beat]);

  // playback
  useEffect(() => {
    if (!playing || !view) return undefined;
    const id = setInterval(() => {
      setBeat((b) => {
        if (b >= view.timeline.length - 1) { setPlaying(false); return b; }
        return b + 1;
      });
    }, speed);
    return () => clearInterval(id);
  }, [playing, speed, view]);

  const scene = useMemo(() => (view ? sceneStateFor(view, beat) : null), [view, beat]);

  // one popup per moment, not one per render
  useEffect(() => {
    if (!view || !scene) return;
    const e = view.timeline[beat];
    if (!e) return;
    if (scene.killed && !shown.current.kill) {
      shown.current.kill = true;
      setNote(scene.verified
        ? { tone: "ok", title: "Kill verified",
            body: "The kill switch fired and the effect was observed. The agent is stopped." }
        : { tone: "warn", title: "Kill lever pulled",
            body: "A lever was pulled and logged, but nothing here observed its effect. " +
                  "A kill is not a kill until docker inspect confirms it — defender/ does " +
                  "that, and it is not built yet." });
    } else if (e.host === "outside.ares.test" && !shown.current.escape) {
      shown.current.escape = true;
      setNote({ tone: "breach", title: "The agent is outside",
                body: "It reached outside.ares.test. The boundary did not hold here — and at " +
                      "this moment nothing had pulled a lever." });
    } else if (e.severity === "fire" && !shown.current.fire) {
      shown.current.fire = true;
      setNote({ tone: "fire", title: "Bait touched",
                body: `${e.text}. Detection is deterministic: the severity comes from the event ` +
                      "source, not from a model." });
    } else if (beat === view.timeline.length - 1 && !shown.current.end) {
      shown.current.end = true;
      setNote({ tone: view.kill.verdict === "contained" ? "ok" : "breach",
                title: view.report.headline, body: view.report.explanation });
    }
  }, [view, beat, scene]);

  const goTo = useCallback((i) => {
    setPlaying(false);
    setBeat((b) => {
      if (!view) return b;
      return Math.max(0, Math.min(i, view.timeline.length - 1));
    });
  }, [view]);

  useEffect(() => {
    const key = (ev) => {
      if (/input|select|textarea/i.test(ev.target.tagName)) return;
      if (ev.key === " ") { ev.preventDefault(); setPlaying((p) => !p); }
      if (ev.key === "ArrowRight") goTo(beat + 1);
      if (ev.key === "ArrowLeft") goTo(beat - 1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [beat, goTo]);

  if (error) return html`<div class="boot error">${error}</div>`;
  if (!runs.length) return html`
    <div class="boot">
      <p>No drills on disk yet.</p>
      <p class="muted">Run <code>./.venv/bin/python scripts/demo_kill.py</code> or
      <code>cd lab && ./selftest.sh</code>, then reload.</p>
    </div>`;
  if (!view || !scene) return html`<div class="boot">loading drill&hellip;</div>`;

  const atEnd = beat >= view.timeline.length - 1;

  return html`
    <div class="app">
      <header class="topbar">
        <div class="brand"><span class="brand-mark"></span>ARES</div>
        <span class="brand-sub">containment fire drill</span>

        <label class="field">drill
          <select value=${runKey} onChange=${(e) => { setPlaying(false); setRunKey(e.target.value); }}>
            ${runs.map((r) => html`
              <option key=${r.key} value=${r.key}>
                ${r.run_id} · ${r.events} events${r.fired ? " · FIRED" : ""}
              </option>`)}
          </select>
        </label>

        <label class=${`field live ${live ? "on" : ""}`}>
          <input type="checkbox" checked=${live} onChange=${(e) => setLive(e.target.checked)} />
          <span class="dot"></span> live tail
        </label>

        <div class="verdict">
          <span class=${`verdict-badge ${view.kill.verdict}`}>${view.report.headline}</span>
          <span class="verdict-note">${view.report.explanation}</span>
        </div>
      </header>

      <main class="stage-area">
        <${Stage} view=${view} beat=${beat} scene=${scene}
                  note=${note} onCloseNote=${() => setNote(null)} />

        <div class="dock left">
          <${ConsolePanel} view=${view} beat=${beat} goTo=${goTo}
                           open=${panels.console} onToggle=${() => togglePanel("console")} />
          <${VulnPanel} view=${view} open=${panels.vulns}
                        onToggle=${() => togglePanel("vulns")}
                        onOpenAll=${() => setModal("vulns")} />
        </div>

        <div class="dock right">
          <${LeverPanel} view=${view} scene=${scene} open=${panels.levers}
                         onToggle=${() => togglePanel("levers")} />
        </div>

      </main>

      <footer class="controls">
        <div class="transport">
          <button class="btn" onClick=${() => { shown.current = {}; setNote(null); goTo(0); }} title="restart">|◀</button>
          <button class="btn" onClick=${() => goTo(beat - 1)} title="back one beat">◀</button>
          <button class="btn primary" onClick=${() => {
            if (atEnd) { shown.current = {}; setBeat(0); }
            setPlaying((p) => !p);
          }}>${playing ? "‖ pause" : "▶ play"}</button>
          <button class="btn" onClick=${() => goTo(beat + 1)} title="forward one beat">▶</button>
          <button class="btn" onClick=${() => goTo(view.timeline.length - 1)} title="jump to end">▶|</button>

          <input class="scrub" type="range" min="0" max=${Math.max(0, view.timeline.length - 1)}
                 value=${beat} onInput=${(e) => goTo(Number(e.target.value))} />

          <label class="field">speed
            <select value=${speed} onChange=${(e) => setSpeed(Number(e.target.value))}>
              <option value="1600">slow</option>
              <option value="900">normal</option>
              <option value="400">fast</option>
              <option value="120">blitz</option>
            </select>
          </label>

          <button class="btn" onClick=${() => setModal("evidence")}>evidence</button>
          <button class="btn" onClick=${() => setModal("report")}>report</button>
        </div>

        <${Timeline} view=${view} beat=${beat} goTo=${goTo} />
        <p class="hint">
          Playback is paced so it can be watched — real events land milliseconds apart.
          The timeline shows true offsets. Space plays, arrows step.
        </p>
      </footer>

      ${modal === "evidence" && html`
        <${Modal} title="Evidence" onClose=${() => setModal(null)}>
          <${EvidenceBody} view=${view} beat=${beat} goTo=${(i) => { goTo(i); setModal(null); }} />
        <//>`}
      ${modal === "vulns" && html`
        <${Modal} title="Vulnerabilities" onClose=${() => setModal(null)}>
          <${VulnBody} view=${view} />
        <//>`}
      ${modal === "report" && html`
        <${Modal} title="Report" onClose=${() => setModal(null)}>
          <${ReportBody} view=${view} />
        <//>`}
    </div>`;
}

ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
