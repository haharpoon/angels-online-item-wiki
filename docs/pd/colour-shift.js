/* Colour-shift hook for SP_ATTRIB_BIAS sprites (pets, mounts, item colour variants).
 * STUB: returns the input unchanged. The real formula file (docs/pd/colour-shift.js, from Fashionista)
 * replaces this file with the same signature:
 *   applyColourShift(imageData, {base, mask}, {section, indices, palette}) -> ImageData
 *   base/mask: raw OBD strings like "0x3f, 0x0, 160" (or null)
 *   indices: Uint8Array of palette indices, same w*h as imageData (0 = transparent)
 *   palette: array of 256 "rrggbb" strings for the source sprite
 * Callers check applyColourShift.isStub to label output as raw colours. */
(function (g) {
  if (typeof g.applyColourShift === 'function' && !g.applyColourShift.isStub) return;
  function applyColourShift(imageData, bias, opts) { return imageData; }
  applyColourShift.isStub = true;
  g.applyColourShift = applyColourShift;
})(typeof window !== 'undefined' ? window : globalThis);
if (typeof module !== 'undefined') module.exports = { applyColourShift: globalThis.applyColourShift };
