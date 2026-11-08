/* The sandbox stage.
 *
 * Draws ART ONLY -- no text. Every label you see is real HTML positioned over
 * the canvas by the React layer, because 6px glyphs stretched by a pixelated
 * upscale are unreadable no matter how carefully they are drawn. The canvas
 * keeps the hard-edged look; the DOM keeps the words legible.
 *
 * The scene never decides anything either. app.js hands it one beat of the
 * run's timeline and it shows where the agent is, what has been dug up, and
 * which kill levers have moved.
 */
(function (global) {
  "use strict";

  var W = 520, H = 348;

  /* The sandbox is the screen. Grass is a border, not a landscape. */
  var FRAME = { x: 16, y: 14, w: 488, h: 286 };   // outer wooden frame
  var RAIL = 11;                                   // frame thickness
  var SAND = {
    x0: FRAME.x + RAIL, y0: FRAME.y + RAIL,
    x1: FRAME.x + FRAME.w - RAIL, y1: FRAME.y + FRAME.h - RAIL
  };
  var GRASS_Y = FRAME.y + FRAME.h + 16;            // where a loose agent stands
  var ESCAPE = { x: 436, y: 334 };

  var C = {
    grass: "#6ab04c", grassDark: "#4e8f3a", grassLite: "#7ec45c",
    railLite: "#d59a52", rail: "#b5793c", railDark: "#7a4a21", railEdge: "#4a2a10",

    /* warmer, more yellow sand, four tones so a mound reads as a mound */
    sand: "#f7dc74", sandDark: "#e3c155", sandDeep: "#c9a338", sandLite: "#fdf0b2",

    red: "#e2504c", blue: "#4a8fd8", yellow: "#f3c33c", green: "#58bf68",
    teal: "#49c2b4", plasticDark: "rgba(0,0,0,0.22)",

    wood: "#8a5a2b", woodDark: "#4a2a10", metal: "#d3dae2", metalDark: "#98a3ae",
    gold: "#e8a33d", ink: "#2e1b0e",
    fire: "#d14732", breach: "#b8306f", grey: "#9a9486", ok: "#5fbf6a",
    trim: "#5aa8e0"
  };

  /* Bait and allowed hosts, as things actually buried in a sandbox.
   * `lx`/`ly` is where the HTML label goes; `role` drives its colour. */
  var STATIONS = [
    { id: "api",       host: "api.acme.test",      x: 86,  y: 252, kind: "bucket",
      color: C.blue,   label: "api",        role: "allowed" },
    { id: "pkg",       host: "pkg.acme.test",      x: 168, y: 212, kind: "bucket",
      color: C.yellow, label: "pkg",        role: "allowed" },
    { id: "grader",    host: "grader.acme.test",   x: 252, y: 258, kind: "chest",
      color: C.wood,   label: "answer key", role: "bait" },
    { id: "metadata",  host: "metadata.ares.test", x: 336, y: 208, kind: "keys",
      color: C.gold,   label: "cloud creds", role: "bait" },
    { id: "board",     host: "board.ares.test",    x: 412, y: 256, kind: "castle",
      color: C.sandLite, label: "public board", role: "bait" },
    { id: "lookalike", host: "evil-acme.test",     x: 452, y: 186, kind: "bucket",
      color: C.red,    label: "look-alike", role: "bait" },
    { id: "outside",   host: "outside.ares.test",  x: ESCAPE.x, y: GRASS_Y + 6,
      kind: "none",    color: C.breach, label: "outside", role: "escape" }
  ];

  function stationFor(host) {
    if (!host) return null;
    for (var i = 0; i < STATIONS.length; i += 1) {
      if (STATIONS[i].host === host) return STATIONS[i];
    }
    if (host.indexOf("http") === 0) return null;          // the LLM upstream
    if (/acme\.test$/.test(host)) return STATIONS[5];      // any other lookalike
    return STATIONS[6];                                    // unknown == outside
  }

  // --- primitives ---------------------------------------------------------

  function px(g, x, y, w, h, color) {
    g.fillStyle = color;
    g.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  function outlined(g, x, y, w, h, fill, line) {
    px(g, x, y, w, h, line);
    px(g, x + 1, y + 1, w - 2, h - 2, fill);
  }

  /* One deterministic pseudo-random stream, so the scatter is identical on
   * every repaint -- decorations that twitch each frame look like noise. */
  function rng(seed) {
    var s = seed;
    return function () {
      s = (s * 1103515245 + 12345) & 0x7fffffff;
      return s / 0x7fffffff;
    };
  }

  // --- the ground ---------------------------------------------------------

  function drawGrass(g) {
    px(g, 0, 0, W, H, C.grass);
    px(g, 0, 0, W, 2, C.grassLite);
    var r = rng(7);
    for (var i = 0; i < 150; i += 1) {
      var x = Math.floor(r() * W), y = Math.floor(r() * H);
      if (x > FRAME.x - 3 && x < FRAME.x + FRAME.w + 3 &&
          y > FRAME.y - 3 && y < FRAME.y + FRAME.h + 3) continue;
      px(g, x, y, 1, 2, r() > 0.5 ? C.grassDark : C.grassLite);
    }
  }

  function drawFrame(g) {
    // plank rail all the way round, mitred at the corners
    outlined(g, FRAME.x, FRAME.y, FRAME.w, FRAME.h, C.rail, C.railEdge);
    px(g, FRAME.x + 2, FRAME.y + 2, FRAME.w - 4, 2, C.railLite);
    px(g, FRAME.x + 2, FRAME.y + FRAME.h - 4, FRAME.w - 4, 2, C.railDark);
    for (var x = FRAME.x + 34; x < FRAME.x + FRAME.w - 10; x += 46) {
      px(g, x, FRAME.y + 2, 1, RAIL - 3, C.railDark);                      // top seams
      px(g, x, FRAME.y + FRAME.h - RAIL + 1, 1, RAIL - 3, C.railDark);     // bottom
    }
    for (var y = FRAME.y + 40; y < FRAME.y + FRAME.h - 10; y += 46) {
      px(g, FRAME.x + 2, y, RAIL - 3, 1, C.railDark);
      px(g, FRAME.x + FRAME.w - RAIL + 1, y, RAIL - 3, 1, C.railDark);
    }
    // corner caps
    [[FRAME.x, FRAME.y], [FRAME.x + FRAME.w - RAIL - 1, FRAME.y],
     [FRAME.x, FRAME.y + FRAME.h - RAIL - 1],
     [FRAME.x + FRAME.w - RAIL - 1, FRAME.y + FRAME.h - RAIL - 1]
    ].forEach(function (c) {
      outlined(g, c[0], c[1], RAIL + 1, RAIL + 1, C.railLite, C.railEdge);
    });
  }

  /* A small heap of sand: three tones, light on top, shadow at the foot. */
  function mound(g, x, y, w, h) {
    px(g, x - w / 2, y - 1, w, 3, C.sandDark);
    for (var i = 0; i < h; i += 1) {
      var rowW = Math.round(w * (1 - i / h));
      px(g, x - rowW / 2, y - 1 - i, rowW, 1, i > h * 0.55 ? C.sandLite : C.sand);
    }
    px(g, x - w / 2, y + 1, w, 1, C.sandDeep);
  }

  function drawSand(g) {
    px(g, SAND.x0, SAND.y0, SAND.x1 - SAND.x0, SAND.y1 - SAND.y0, C.sand);
    // inner shadow under the rail, so the pit has depth rather than being a swatch
    px(g, SAND.x0, SAND.y0, SAND.x1 - SAND.x0, 4, C.sandDark);
    px(g, SAND.x0, SAND.y0, 3, SAND.y1 - SAND.y0, C.sandDark);
    px(g, SAND.x0, SAND.y1 - 2, SAND.x1 - SAND.x0, 2, C.sandLite);

    var r = rng(19);

    // Broad dunes first: without them the pit is one flat swatch. Built as
    // stacked rows that taper at both ends -- a plain filled rectangle of
    // lighter sand reads as a slab lying on the surface, not as a rise in it.
    for (var b = 0; b < 30; b += 1) {
      var bx = SAND.x0 + 10 + Math.floor(r() * (SAND.x1 - SAND.x0 - 20));
      var by = SAND.y0 + 10 + Math.floor(r() * (SAND.y1 - SAND.y0 - 18));
      var bw = 18 + Math.floor(r() * 30);
      var bh = 3 + Math.floor(r() * 4);
      var lift = r() > 0.45;
      for (var row = 0; row < bh; row += 1) {
        var inset = Math.round((bw / 2) * (row / bh) * 0.8);
        px(g, bx + inset, by + row, bw - inset * 2, 1,
           lift ? C.sandLite : C.sandDark);
      }
      px(g, bx + 3, by + bh, bw - 6, 1, lift ? C.sandDark : C.sandDeep);
    }

    // rake ripples: short dashes with gaps, so they suggest a dragged rake
    // instead of ruled lines across the pit
    for (var k = 0; k < 10; k += 1) {
      var ry = SAND.y0 + 14 + k * 26;
      for (var rx = SAND.x0 + 8; rx < SAND.x1 - 8; rx += 7) {
        if ((rx + k * 11) % 21 < 7) continue;        // break the line up
        var wobble = Math.round(Math.sin((rx + k * 23) / 16) * 3);
        px(g, rx, ry + wobble, 3, 1, C.sandDark);
        px(g, rx, ry + wobble + 1, 3, 1, C.sandLite);
      }
    }

    // grain
    for (var i = 0; i < 1100; i += 1) {
      var gx = SAND.x0 + 4 + Math.floor(r() * (SAND.x1 - SAND.x0 - 8));
      var gy = SAND.y0 + 6 + Math.floor(r() * (SAND.y1 - SAND.y0 - 10));
      var tone = r();
      px(g, gx, gy, 1, 1, tone > 0.70 ? C.sandLite : (tone > 0.34 ? C.sandDark : C.sandDeep));
    }

    // mini piles, scattered but never on top of a station
    var piles = [[62, 196], [118, 278], [204, 198], [292, 226], [302, 286],
                 [370, 286], [386, 188], [460, 250], [148, 168], [236, 166],
                 [74, 232], [348, 230], [430, 196], [268, 290], [186, 240],
                 [128, 200], [418, 290], [62, 268], [224, 262], [330, 172],
                 [476, 200], [94, 160], [392, 254], [158, 296]];
    piles.forEach(function (pt, i) {
      mound(g, pt[0], pt[1], 15 + (i % 4) * 6, 6 + (i % 3) * 3);
    });
  }

  // --- plastic toys -------------------------------------------------------

  function bucket(g, x, y, color, cracked) {
    var top = y - 22, h = 22;
    // tapered body
    for (var i = 0; i < h; i += 1) {
      var w = Math.round(22 - i * 0.30);
      px(g, x - w / 2, top + i, w, 1, i > h - 5 ? C.plasticDark : color);
    }
    px(g, x - 12, top - 3, 24, 4, color);                    // rim
    px(g, x - 12, top - 3, 24, 1, "rgba(255,255,255,0.45)");
    px(g, x - 6, top + 3, 2, 13, "rgba(255,255,255,0.35)");  // highlight
    // handle
    px(g, x - 14, top - 9, 2, 7, C.metalDark);
    px(g, x + 12, top - 9, 2, 7, C.metalDark);
    px(g, x - 14, top - 10, 28, 2, C.metalDark);
    if (cracked) {
      px(g, x + 1, top + 4, 1, 6, C.railEdge);
      px(g, x + 2, top + 9, 1, 5, C.railEdge);
      px(g, x - 1, top + 12, 2, 1, C.railEdge);
    }
  }

  function spade(g, x, y, angle, color) {
    g.save();
    g.translate(Math.round(x), Math.round(y));
    g.rotate(angle);
    px(g, -1, -24, 3, 20, color);                 // handle
    px(g, -4, -27, 9, 4, color);                  // grip
    px(g, -5, -5, 11, 11, C.metal);               // blade
    px(g, -5, 4, 11, 2, C.metalDark);
    g.restore();
  }

  function rake(g, x, y, color) {
    px(g, x - 1, y - 24, 3, 20, color);
    px(g, x - 4, y - 27, 9, 4, color);
    px(g, x - 9, y - 6, 19, 3, color);
    for (var i = 0; i < 4; i += 1) px(g, x - 7 + i * 5, y - 3, 2, 5, color);
  }

  function starMold(g, x, y, color) {
    px(g, x - 2, y - 11, 5, 11, color);
    px(g, x - 9, y - 7, 19, 4, color);
    px(g, x - 7, y - 3, 4, 5, color);
    px(g, x + 4, y - 3, 4, 5, color);
    px(g, x - 2, y - 11, 5, 1, "rgba(255,255,255,0.4)");
  }

  function sieve(g, x, y, color) {
    outlined(g, x - 10, y - 9, 21, 11, color, C.plasticDark);
    for (var i = 0; i < 4; i += 1) {
      for (var j = 0; j < 2; j += 1) {
        px(g, x - 7 + i * 5, y - 6 + j * 4, 2, 2, C.sandDeep);
      }
    }
    px(g, x + 10, y - 8, 7, 2, color);
  }

  /* Scenery, not stations: nothing here is clickable or meaningful. */
  function drawToys(g) {
    spade(g, 118, 238, -0.35, C.red);
    rake(g, 350, 278, C.teal);
    starMold(g, 212, 288, C.green);
    starMold(g, 468, 274, C.blue);
    sieve(g, 282, 190, C.red);
    bucket(g, 56, 290, C.green, false);
    bucket(g, 486, 214, C.teal, false);
    spade(g, 398, 170, 0.5, C.yellow);
  }

  // --- stations -----------------------------------------------------------

  function buried(g, x, y) {
    // an undug station: just a lump with a corner showing
    mound(g, x, y, 26, 9);
    px(g, x - 4, y - 7, 8, 3, C.sandDeep);
  }

  function chest(g, x, y, open, t) {
    px(g, x - 15, y - 1, 30, 3, C.sandDark);
    outlined(g, x - 14, y - 14, 28, 14, "#8a5a2b", C.woodDark);
    px(g, x - 12, y - 8, 24, 2, C.railDark);
    if (open) {
      outlined(g, x - 14, y - 28, 28, 11, "#a9703c", C.woodDark);
      px(g, x - 3, y - 11, 7, 9, C.gold);
      var lift = (t / 220 | 0) % 3;
      px(g, x - 8, y - 36 - lift, 17, 3, C.gold);
      px(g, x - 5, y - 40 - lift, 11, 2, C.gold);
    } else {
      outlined(g, x - 14, y - 22, 28, 9, "#a9703c", C.woodDark);
      px(g, x - 3, y - 17, 7, 7, C.gold);
    }
  }

  function keyring(g, x, y, found, t) {
    px(g, x - 11, y - 1, 22, 3, C.sandDark);
    outlined(g, x - 11, y - 18, 23, 18, found ? "#33406b" : "#2a3350", C.woodDark);
    px(g, x - 8, y - 15, 17, 10, "#0d1324");
    if (found) {
      for (var i = 0; i < 3; i += 1) {
        px(g, x - 6, y - 13 + i * 3, ((t / 170 + i) | 0) % 2 ? 8 : 12, 2, C.ok);
      }
      px(g, x + 12, y - 24, 5, 5, C.gold);              // key popping out
      px(g, x + 16, y - 23, 5, 2, C.gold);
      px(g, x + 19, y - 22, 2, 3, C.gold);
    } else {
      px(g, x - 6, y - 12, 12, 2, "#4a567f");
    }
  }

  function castle(g, x, y, posted) {
    px(g, x - 17, y - 1, 34, 3, C.sandDeep);
    outlined(g, x - 16, y - 13, 33, 13, C.sand, C.sandDeep);
    px(g, x - 15, y - 12, 31, 2, C.sandLite);
    [-13, -1, 11].forEach(function (dx) {              // turrets
      outlined(g, x + dx, y - 24, 8, 13, C.sand, C.sandDeep);
      px(g, x + dx + 1, y - 23, 6, 2, C.sandLite);
      px(g, x + dx, y - 27, 3, 4, C.sand);
      px(g, x + dx, y - 27, 3, 1, C.sandDeep);
      px(g, x + dx + 5, y - 27, 3, 4, C.sand);
      px(g, x + dx + 5, y - 27, 3, 1, C.sandDeep);
    });
    px(g, x - 1, y - 42, 2, 16, C.wood);                // flagpole
    px(g, x + 1, y - 42, 12, 8, posted ? C.breach : "#efe6cd");
    px(g, x + 1, y - 42, 12, 1, C.woodDark);
    px(g, x - 5, y - 9, 10, 9, C.sandDeep);             // gate
  }

  function drawStation(g, s, found, t) {
    if (s.kind === "none") return;
    if (s.kind === "bucket") {
      bucket(g, s.x, s.y, s.color, s.id === "lookalike");
      if (found && s.id === "pkg") {                    // the fetch-through hose
        px(g, s.x + 11, s.y - 16, 26, 3, C.trim);
        px(g, s.x + 35, s.y - 30, 3, 15, C.trim);
        px(g, s.x + 33, s.y - 33, 7, 4, C.trim);
      }
      if (found && s.id === "lookalike") {
        px(g, s.x - 13, s.y - 27, 26, 2, C.fire);
      }
      return;
    }
    if (!found) { buried(g, s.x, s.y); return; }
    if (s.kind === "chest") chest(g, s.x, s.y, true, t);
    else if (s.kind === "keys") keyring(g, s.x, s.y, true, t);
    else if (s.kind === "castle") castle(g, s.x, s.y, true);
  }

  /* A station that has been dug reveals itself; before that it is a lump,
   * except the two allowlisted buckets, which were never hidden. */
  function drawStations(g, found, t) {
    STATIONS.forEach(function (s) {
      if (s.kind === "chest" && !found[s.id]) { buried(g, s.x, s.y); return; }
      if (s.kind === "keys" && !found[s.id]) { buried(g, s.x, s.y); return; }
      if (s.kind === "castle" && !found[s.id]) { castle(g, s.x, s.y, false); return; }
      drawStation(g, s, !!found[s.id], t);
    });
  }

  function drawHoles(g, holes) {
    holes.forEach(function (p) {
      px(g, p[0] - 13, p[1] - 3, 27, 7, C.sandDeep);
      px(g, p[0] - 10, p[1] - 2, 21, 4, "#a8812f");
      mound(g, p[0] - 19, p[1] + 1, 15, 6);
      mound(g, p[0] + 19, p[1] + 1, 15, 6);
    });
  }

  // --- the boundary -------------------------------------------------------

  function drawBoundary(g, crossed, t) {
    if (!crossed) return;
    var y = FRAME.y + FRAME.h;
    px(g, FRAME.x, y - 2, FRAME.w, 3, C.breach);
    for (var i = 0; i < 7; i += 1) {
      var yy = y + 8 + ((t / 70 + i * 13) % 26);
      px(g, ESCAPE.x - 28 + i * 9, yy, 2, 2, C.breach);
    }
  }

  // --- the agent ----------------------------------------------------------

  function drawShovel(g, x, y, swing, flipped) {
    var dir = flipped ? -1 : 1;
    g.save();
    g.translate(Math.round(x), Math.round(y));
    g.rotate(dir * swing);
    px(g, 0, -4, 2 * dir, 15, "#c0862f");            // handle
    px(g, -1 * dir, -7, 4 * dir, 3, "#c0862f");      // grip
    px(g, -2 * dir, 10, 6 * dir, 7, C.metal);        // blade
    px(g, -2 * dir, 16, 6 * dir, 2, C.metalDark);
    g.restore();
  }

  function drawAgent(g, sprites, s, t) {
    var flipped = s.facing < 0;
    var sprite = sprites.front;
    if (s.pose === "dig") sprite = sprites.dig;
    if (s.frozen) sprite = s.pose === "dig" ? sprites.dig_frozen : sprites.front_frozen;
    else if (flipped) sprite = s.pose === "dig" ? sprites.dig_flip : sprites.front_flip;
    if (!sprite) return;

    var w = sprite.width, h = sprite.height;
    var bob = s.frozen ? 0 : Math.round(Math.sin(t / (s.pose === "walk" ? 110 : 330)) * 1.5);
    var swing = s.pose === "dig" && !s.frozen ? Math.sin(t / 95) * 0.7 + 0.45 : 0.15;
    var shake = s.alarm && !s.frozen ? Math.round(Math.sin(t / 40) * 2) : 0;
    var x = Math.round(s.x - w / 2) + shake;
    var y = Math.round(s.y - h) + bob;

    g.fillStyle = "rgba(0,0,0,0.20)";
    g.fillRect(x + 4, Math.round(s.y) - 3, w - 8, 4);

    // Poyo carries the shovel the whole time, not only mid-dig.
    drawShovel(g, s.x + (flipped ? -13 : 13), y + h * 0.56, swing, flipped);
    g.drawImage(sprite, x, y);

    if (s.frozen) {                                   // docker_pause idiom
      px(g, s.x - 6, y - 11, 3, 9, "#f3e3bf");
      px(g, s.x + 2, y - 11, 3, 9, "#f3e3bf");
      px(g, s.x - 7, y - 12, 13, 1, C.railEdge);
    }
  }

  // --- scene --------------------------------------------------------------

  function Scene(canvas, sprites) {
    this.canvas = canvas;
    this.g = canvas.getContext("2d");
    this.g.imageSmoothingEnabled = false;
    this.sprites = sprites;
    this.agent = { x: STATIONS[0].x, y: STATIONS[0].y, facing: 1, pose: "idle" };
    this.target = { x: STATIONS[0].x, y: STATIONS[0].y };
    this.state = { found: {}, levers: [], holes: [] };
    this.t0 = performance.now();
    this.raf = null;
  }

  Scene.prototype.setState = function (state) {
    this.state = state;
    var station = stationFor(state.host);
    if (state.escaped) station = STATIONS[6];
    if (station) {
      var nx = station.id === "outside" ? ESCAPE.x : station.x;
      var ny = station.id === "outside" ? ESCAPE.y : station.y;
      if (nx !== this.target.x) this.agent.facing = nx > this.agent.x ? 1 : -1;
      this.target = { x: nx, y: ny };
    }
  };

  Scene.prototype.snap = function () {
    this.agent.x = this.target.x;
    this.agent.y = this.target.y;
  };

  Scene.prototype.start = function () {
    var self = this;
    (function frame(now) {
      self.draw(now - self.t0);
      self.raf = requestAnimationFrame(frame);
    })(performance.now());
  };

  Scene.prototype.stop = function () {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = null;
  };

  Scene.prototype.draw = function (t) {
    var g = this.g, s = this.state, a = this.agent;

    var dx = this.target.x - a.x, dy = this.target.y - a.y;
    if (!s.frozen && (Math.abs(dx) > 1.5 || Math.abs(dy) > 1.5)) {
      a.x += Math.max(-2.8, Math.min(2.8, dx * 0.16));
      a.y += Math.max(-1.8, Math.min(1.8, dy * 0.16));
      a.pose = "walk";
    } else {
      a.x = this.target.x;
      a.y = this.target.y;
      a.pose = s.digging ? "dig" : "idle";
    }

    g.clearRect(0, 0, W, H);
    drawGrass(g);
    drawFrame(g);
    drawSand(g);
    drawHoles(g, s.holes || []);
    drawToys(g);
    drawStations(g, s.found || {}, t);
    drawBoundary(g, !!(s.found || {}).outside, t);
    drawAgent(g, this.sprites, {
      x: a.x, y: a.y, facing: a.facing, pose: a.pose,
      alarm: s.alarm, frozen: s.frozen
    }, t);

    if (s.alarm) {   // the fire beat, unmissable
      g.fillStyle = "rgba(209,71,50," + (0.13 + 0.10 * Math.sin(t / 90)) + ")";
      g.fillRect(0, 0, W, H);
    }
  };

  Scene.WIDTH = W;
  Scene.HEIGHT = H;
  Scene.STATIONS = STATIONS;
  Scene.stationFor = stationFor;
  Scene.ESCAPE = ESCAPE;
  Scene.COLORS = C;
  global.Scene = Scene;
})(window);
