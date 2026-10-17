# Pet viewer pipeline (docs/pets.html)

All game files are read-only inputs; nothing here writes to a .pak or the client install.

1. `parse_src.py` – parses `pet.xml` (UPDATE24 eng, 1,703 forms) and `NPC.OBD` (update26) into `build/pets_raw.json`, `build/obd.json`, and the list of needed `.spr` files.
2. Manifests – `ao_unpacker.py <pak> --manifest-only` for every pak (Global install: data1-3/update/update2; legacy client: data1, update, update2-3, UPDATE4-26).
3. `locate.py` – picks the newest pak that holds each needed sprite and writes `build/src_map.json`.
4. `pak_extract.py jobs.json out/` – inflates just those members (raw DEFLATE at the manifest offset), opening paks with `rb` only.
5. `build_pets.py docs/pets docs/items.html` – decodes every EWSP `.spr`, writes one sheet per sprite file (deduped by content hash) and `pets-data.js`.

## Sheet format
`docs/pets/sheets/<hash>.png` is an 8-bit greyscale PNG whose pixel value **is the palette index** (0 = transparent).
It is both the sprite sheet and the palette-index mask. Rows are animation phases, columns are the 5 stored directions
(0 back, 1 back-left, 2 left, 3 front-left, 4 front); frame = phase*5 + dir. The viewer mirrors 3/2/1 for the right side
and draws each frame at origin minus its TLHS anchor (bytes 28/32). Palettes (RGB565 decoded to hex) are in `pets-data.js`.

## Colour shift
Forms keep raw `baseBias` / `maskBias` strings from NPC.OBD plus `biasFlag` (SP_ATTRIB_BIAS). The viewer calls
`applyColourShift(imageData, {base, mask}, {section:'pet', indices, palette})` from `docs/pd/colour-shift.js`.
That file is currently a stub (`applyColourShift.isStub = true`) that returns its input, and the page says so;
dropping in the real formula file needs no viewer change.
