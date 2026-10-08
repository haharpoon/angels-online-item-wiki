"""Decode Angels Online EWSP Wait.spr the same way angelsonline.wiki does.

Each file is EWSP + 15 TLHS frames (5 directions x 3 idle phases).
Span records are int16 count, int16 dest_x, uint32 src — not x/width.
Palette is shared RGB565 at the EWSP header offset.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

from shp_icon import rgb565


def tlhs_starts(data: bytes) -> list[int]:
    starts = []
    pos = 0
    while True:
        i = data.find(b"TLHS", pos)
        if i < 0:
            break
        starts.append(i)
        pos = i + 4
    return starts


def ewsp_palette(data: bytes) -> list[tuple[int, int, int]]:
    pal_off = struct.unpack_from("<I", data, 16)[0] if len(data) >= 20 else 0
    pal = [(0, 0, 0)] * 256
    if pal_off <= 0:
        return pal
    for i in range(256):
        o = pal_off + i * 2
        if o + 2 <= len(data):
            pal[i] = rgb565(struct.unpack_from("<H", data, o)[0])
    return pal


def decode_frame(data: bytes, start: int, pal: list[tuple[int, int, int]]) -> tuple[Image.Image, int, int] | None:
    if start + 80 > len(data) or data[start:start + 4] != b"TLHS":
        return None
    w, h = struct.unpack_from("<II", data, start + 20)
    hx, hy = struct.unpack_from("<ii", data, start + 28)
    px_off = struct.unpack_from("<I", data, start + 44)[0]
    if w <= 0 or h <= 0 or w > 512 or h > 512:
        return None
    offs = [struct.unpack_from("<I", data, start + 80 + y * 4)[0] for y in range(h)]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = img.load()
    for y in range(h):
        row_start = start + offs[y]
        row_end = start + (offs[y + 1] if y + 1 < h else px_off)
        p = row_start
        while p + 8 <= row_end and p + 8 <= len(data):
            count, dest_x = struct.unpack_from("<hh", data, p)
            src = struct.unpack_from("<I", data, p + 4)[0]
            p += 8
            if count < 0:
                break
            src_abs = start + src
            for k in range(count):
                xx = dest_x + k
                if xx < 0 or xx >= w or src_abs + k >= len(data):
                    break
                idx = data[src_abs + k]
                if idx == 0:
                    continue
                pix[xx, y] = (*pal[idx], 255)
    return img, hx, hy


def decode_wait(path: Path) -> list[dict] | None:
    data = path.read_bytes()
    if data[:4] != b"EWSP":
        return None
    pal = ewsp_palette(data)
    starts = tlhs_starts(data)
    if len(starts) < 5:
        return None
    frames = []
    for i, start in enumerate(starts[:15]):
        got = decode_frame(data, start, pal)
        if not got:
            continue
        img, hx, hy = got
        phase, direction = divmod(i, 5)
        frames.append({
            "index": i, "phase": phase, "direction": direction,
            "image": img, "anchorX": hx, "anchorY": hy,
            "width": img.size[0], "height": img.size[1],
        })
    return frames or None


def pack_atlas(frames: list[dict]) -> tuple[Image.Image, list[dict], int, int]:
    by_index = {f["index"]: f for f in frames}
    cell_w = max(f["width"] for f in frames)
    cell_h = max(f["height"] for f in frames)
    atlas = Image.new("RGBA", (cell_w * 5, cell_h * 3), (0, 0, 0, 0))
    meta = []
    first = frames[0]
    for i in range(15):
        phase, direction = divmod(i, 5)
        src = by_index.get(i) or first
        x, y = direction * cell_w, phase * cell_h
        atlas.paste(src["image"], (x, y), src["image"])
        meta.append({
            "index": i, "phase": phase, "direction": direction,
            "x": x, "y": y, "width": src["width"], "height": src["height"],
            "anchorX": src["anchorX"], "anchorY": src["anchorY"],
        })
    return atlas, meta, cell_w, cell_h
