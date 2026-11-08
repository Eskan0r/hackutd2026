/* Sprite loading for the Ares stage.
 *
 * The character art is pixel art that was exported upscaled -- 536x592 for a
 * drawing whose real grid is much smaller. Drawing that into a 400x240 scene
 * means a fractional downscale, which smears the hard edges the whole look
 * depends on. So instead of guessing the export factor, recover it: in true
 * pixel art every horizontal run of identical pixels is a multiple of the
 * block size, so the GCD of all run lengths IS the block size. Then resample
 * one pixel per block and we are back on the artist's original grid.
 */
(function (global) {
  "use strict";

  function gcd(a, b) { while (b) { var t = a % b; a = b; b = t; } return a; }

  function detectBlockSize(data, w, h) {
    var g = 0;
    for (var y = 0; y < h; y += 1) {
      var runStart = 0;
      for (var x = 1; x <= w; x += 1) {
        var same = false;
        if (x < w) {
          var a = (y * w + x) * 4, b = (y * w + x - 1) * 4;
          same = data[a] === data[b] && data[a + 1] === data[b + 1] &&
                 data[a + 2] === data[b + 2] && data[a + 3] === data[b + 3];
        }
        if (!same) {
          g = gcd(g, x - runStart);
          runStart = x;
          if (g === 1) return 1;   // native resolution already
        }
      }
    }
    return g || 1;
  }

  /* Trim fully transparent margins so the sprite's feet sit where we put them
   * rather than wherever the export happened to pad to. */
  function contentBox(data, w, h) {
    var x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (var y = 0; y < h; y += 1) {
      for (var x = 0; x < w; x += 1) {
        if (data[(y * w + x) * 4 + 3] > 8) {
          if (x < x0) x0 = x;
          if (x > x1) x1 = x;
          if (y < y0) y0 = y;
          if (y > y1) y1 = y;
        }
      }
    }
    if (x1 < 0) return { x: 0, y: 0, w: w, h: h };
    return { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
  }

  function toCanvas(img) {
    var c = document.createElement("canvas");
    c.width = img.width; c.height = img.height;
    var g = c.getContext("2d", { willReadFrequently: true });
    g.imageSmoothingEnabled = false;
    g.drawImage(img, 0, 0);
    return { canvas: c, ctx: g };
  }

  /* Resample to the native grid, sampling the centre of each block so a stray
   * edge pixel cannot decide a whole block's colour. */
  function downscale(src, srcCtx, block, box) {
    var w = Math.max(1, Math.round(box.w / block));
    var h = Math.max(1, Math.round(box.h / block));
    var out = document.createElement("canvas");
    out.width = w; out.height = h;
    var octx = out.getContext("2d");
    var image = octx.createImageData(w, h);
    var srcData = srcCtx.getImageData(box.x, box.y, box.w, box.h).data;
    for (var y = 0; y < h; y += 1) {
      for (var x = 0; x < w; x += 1) {
        var sx = Math.min(box.w - 1, Math.floor(x * block + block / 2));
        var sy = Math.min(box.h - 1, Math.floor(y * block + block / 2));
        var s = (sy * box.w + sx) * 4, d = (y * w + x) * 4;
        image.data[d] = srcData[s];
        image.data[d + 1] = srcData[s + 1];
        image.data[d + 2] = srcData[s + 2];
        image.data[d + 3] = srcData[s + 3];
      }
    }
    octx.putImageData(image, 0, 0);
    return out;
  }

  function flip(canvas) {
    var out = document.createElement("canvas");
    out.width = canvas.width; out.height = canvas.height;
    var g = out.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.translate(canvas.width, 0);
    g.scale(-1, 1);
    g.drawImage(canvas, 0, 0);
    return out;
  }

  /* A flat silhouette of the sprite, for the "paused / frozen" state. */
  function tint(canvas, rgb, alpha) {
    var out = document.createElement("canvas");
    out.width = canvas.width; out.height = canvas.height;
    var g = out.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.drawImage(canvas, 0, 0);
    g.globalCompositeOperation = "source-atop";
    g.globalAlpha = alpha === undefined ? 0.55 : alpha;
    g.fillStyle = rgb;
    g.fillRect(0, 0, out.width, out.height);
    return out;
  }

  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error("sprite failed: " + src)); };
      img.src = src;
    });
  }

  /* Nearest-neighbour shrink to fit a height budget, for art that turns out
   * to already be at native resolution (block size 1) or is simply huge. An
   * integer step keeps edges hard instead of smearing them. */
  function fitHeight(canvas, maxH) {
    if (canvas.height <= maxH) return canvas;
    var step = Math.ceil(canvas.height / maxH);
    var w = Math.max(1, Math.floor(canvas.width / step));
    var h = Math.max(1, Math.floor(canvas.height / step));
    var src = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
    var out = document.createElement("canvas");
    out.width = w; out.height = h;
    var octx = out.getContext("2d");
    var image = octx.createImageData(w, h);
    for (var y = 0; y < h; y += 1) {
      for (var x = 0; x < w; x += 1) {
        var s = ((y * step) * canvas.width + x * step) * 4, d = (y * w + x) * 4;
        image.data[d] = src[s];
        image.data[d + 1] = src[s + 1];
        image.data[d + 2] = src[s + 2];
        image.data[d + 3] = src[s + 3];
      }
    }
    octx.putImageData(image, 0, 0);
    return out;
  }

  function prepare(img, maxH) {
    var holder = toCanvas(img);
    var full = holder.ctx.getImageData(0, 0, img.width, img.height).data;
    var box = contentBox(full, img.width, img.height);
    var crop = holder.ctx.getImageData(box.x, box.y, box.w, box.h).data;
    var block = detectBlockSize(crop, box.w, box.h);
    // A block bigger than the art makes no sense; cap it so a weird export
    // cannot collapse the sprite to a few pixels.
    block = Math.max(1, Math.min(block, Math.floor(Math.min(box.w, box.h) / 8) || 1));
    return fitHeight(downscale(holder.canvas, holder.ctx, block, box), maxH || 86);
  }

  global.Sprites = {
    load: function (sources, maxH) {
      var names = Object.keys(sources);
      return Promise.all(names.map(function (n) { return loadImage(sources[n]); }))
        .then(function (images) {
          var out = {};
          images.forEach(function (img, i) {
            var sprite = prepare(img, maxH);
            out[names[i]] = sprite;
            out[names[i] + "_flip"] = flip(sprite);
            out[names[i] + "_frozen"] = tint(sprite, "#6f7fa8", 0.6);
          });
          return out;
        });
    },
    detectBlockSize: detectBlockSize,
    prepare: prepare
  };
})(window);
