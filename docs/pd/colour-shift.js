/* Angels Online BaseBias / MaskBias recolour (reverse-engineered).
 *
 * Field (char*.obd [OBJECT], NPC.OBD, itemicon.xml basebias/basecolor/baserange):
 *   BaseBias = 0xLLSSHH, 0xCCCC, RR     MaskBias = same layout
 *   HH  byte0  0..63 (64==0)  ABSOLUTE target hue, 64 steps / 360deg
 *   SS  byte1  signed -32..32  HSV saturation delta  (/32)
 *   LL  byte2  signed -32..32  HSV value delta       (/32)
 *   CCCC RGB565 reference colour, 0 = none
 *   RR  bit7 = flag (ignored); RR & 0x7f = hue tolerance in 1/64 steps (>=32 or no colour: whole section)
 * Section: sprite palette indices 1..63 -> MaskBias, 64..255 -> BaseBias.
 */
(function (root) {
  function s8(b) { return b > 127 ? b - 256 : b; }
  function parseBias(v) {
    if (!v) return null;
    if (typeof v === 'object') return v;
    const p = String(v).split(',').map(x => x.trim());
    const n = parseInt(p[0], 16);
    return { l: s8((n >> 16) & 255), s: s8((n >> 8) & 255), h: (n & 255) % 64,
             color: p[1] ? parseInt(p[1], 16) : 0, range: p[2] ? parseInt(p[2], 10) : 160 };
  }
  function rgb565(c) { return [((c >> 11) & 31) * 255 / 31 | 0, ((c >> 5) & 63) * 255 / 63 | 0, (c & 31) * 255 / 31 | 0]; }
  function rgb2hsv(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = 0;
    if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    h /= 6; if (h < 0) h += 1;
    return [h, mx ? d / mx : 0, mx];
  }
  function rgb2hlsSat(r, g, b) { // HLS saturation, used only for selection (matches Python ref)
    r /= 255; g /= 255; b /= 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
    return d === 0 ? 0 : l <= 0.5 ? d / (mx + mn) : d / (2 - mx - mn);
  }
  function hsv2rgb(h, s, v) {
    const i = Math.floor(h * 6), f = h * 6 - i, p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
    const m = [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][((i % 6) + 6) % 6];
    return [Math.round(m[0] * 255), Math.round(m[1] * 255), Math.round(m[2] * 255)];
  }
  const clamp = x => x < 0 ? 0 : x > 1 ? 1 : x;
  function selected(r, g, b, bias) {
    const tol = bias.range & 0x7f;
    if (tol >= 32 || !bias.color) return true;
    const ref = rgb565(bias.color), rh = rgb2hsv(ref[0], ref[1], ref[2])[0], rs = rgb2hlsSat(ref[0], ref[1], ref[2]);
    const s = rgb2hlsSat(r, g, b);
    if (rs < 0.08) return s < 0.15;
    if (s < 0.08) return false;
    let d = Math.abs(rgb2hsv(r, g, b)[0] - rh) * 64; d = Math.min(d, 64 - d);
    return d <= tol;
  }
  function shiftRGB(r, g, b, bias) {
    const hsv = rgb2hsv(r, g, b);
    return hsv2rgb(bias.h / 64, clamp(hsv[1] + bias.s / 32), clamp(hsv[2] + bias.l / 32));
  }
  /** Recolour a 256-entry palette ([[r,g,b],...]). Cheapest path; use if sprites ship as indexed data. */
  function applyColourShiftToPalette(palette, shiftValues) {
    const base = parseBias(shiftValues && shiftValues.base), mask = parseBias(shiftValues && shiftValues.mask);
    return palette.map((c, i) => {
      const b = i === 0 ? null : i < 64 ? mask : base;
      return b && selected(c[0], c[1], c[2], b) ? shiftRGB(c[0], c[1], c[2], b) : c.slice();
    });
  }
  function toRGB(c) { return typeof c === 'string' ? [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)] : c; }
  /**
   * applyColourShift(imageData, {base, mask}, opts) -> ImageData (modified in place)
   * base/mask: raw OBD strings like "0x3f, 0x0, 160" (or parsed objects / null)
   * opts.indices: Uint8Array of palette indices (w*h). 0 = transparent (untouched),
   *   1..63 -> MaskBias, 64..255 -> BaseBias (each only within its colour/tolerance).
   * opts.palette: 256 "rrggbb" strings or [r,g,b] arrays (source palette).
   * Without indices: opts.section as a per-pixel mask flag array/ImageData, else greys = mask (icon heuristic).
   */
  function applyColourShift(imageData, shiftValues, opts) {
    opts = opts || {};
    const base = parseBias(shiftValues && shiftValues.base), mask = parseBias(shiftValues && shiftValues.mask);
    if (!base && !mask) return imageData;
    const d = imageData.data, idx = opts.indices;
    if (idx && opts.palette) {
      const lut = applyColourShiftToPalette(opts.palette.map(toRGB), { base, mask });
      for (let px = 0, i = 0; px < idx.length; px++, i += 4) {
        const v = idx[px]; if (!v) continue;
        const c = lut[v]; d[i] = c[0]; d[i + 1] = c[1]; d[i + 2] = c[2];
      }
      return imageData;
    }
    const sec = opts.section && typeof opts.section === 'object' ? opts.section : null, secIsImg = sec && sec.data;
    const cache = new Map();
    for (let i = 0, px = 0; i < d.length; i += 4, px++) {
      if (!d[i + 3]) continue;
      const r = d[i], g = d[i + 1], b = d[i + 2];
      const isMask = idx ? (idx[px] > 0 && idx[px] < 64) : sec ? (secIsImg ? sec.data[px * 4 + 3] > 0 : sec[px] > 0) : rgb2hlsSat(r, g, b) < 0.15;
      const bias = isMask ? mask : base;
      if (!bias) continue;
      const key = (isMask ? 1 << 24 : 0) | (r << 16) | (g << 8) | b;
      let out = cache.get(key);
      if (out === undefined) { out = selected(r, g, b, bias) ? shiftRGB(r, g, b, bias) : null; cache.set(key, out); }
      if (out) { d[i] = out[0]; d[i + 1] = out[1]; d[i + 2] = out[2]; }
    }
    return imageData;
  }
  applyColourShift.isStub = false;
  const api = { applyColourShift, applyColourShiftToPalette, parseBias };
  Object.assign(root, api);
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
