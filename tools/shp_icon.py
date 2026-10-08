"""Decode Midage TLHS item icons (shape/item/i####.SHP) to PNG.

Last-pak-wins, same order as extract_content.py. Multi-direction sheets
keep the cell with the most pixels in the upper half (facing the camera);
the in-game default is often the back view.
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

PAK_ORDER = (
    ["data1", "update", "update2", "update3"]
    + [f"UPDATE{i}" for i in range(4, 22)]
    + [f"update{i}" for i in range(22, 27)]
)


def rgb565(c: int) -> tuple[int, int, int]:
    r = ((c >> 11) & 31) * 255 // 31
    g = ((c >> 5) & 63) * 255 // 63
    b = (c & 31) * 255 // 31
    return r, g, b


def _row_spans(data: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    spans = []
    p = start
    while p + 8 <= end and p + 8 <= len(data):
        x, width = struct.unpack_from("<hh", data, p)
        src = struct.unpack_from("<I", data, p + 4)[0]
        p += 8
        if width == -1:
            break
        spans.append((x, width, src))
    return spans


def decode_shp_bytes(data: bytes, front: bool = True) -> Image.Image | None:
    if data[:4] != b"TLHS" or len(data) < 80:
        return None
    frames, _pal_size, _flag, w, h = struct.unpack_from("<IIIII", data, 8)
    px_off = struct.unpack_from("<I", data, 44)[0]
    pal_off = struct.unpack_from("<I", data, 64)[0]
    if w <= 0 or h <= 0 or w > 512 or h > 512:
        return None
    if pal_off >= len(data) or 80 + h * 4 > len(data):
        return None
    palette = [(0, 0, 0)] * 256
    pal_end = px_off if px_off > pal_off else min(len(data), pal_off + 512)
    n = min(256, max(0, (pal_end - pal_off) // 2))
    for i in range(n):
        palette[i] = rgb565(struct.unpack_from("<H", data, pal_off + i * 2)[0])

    offs = [struct.unpack_from("<I", data, 80 + i * 4)[0] for i in range(h)]
    rows = []
    for y in range(h):
        start = offs[y]
        end = offs[y + 1] if y + 1 < h else pal_off
        if start < 0 or start > len(data):
            rows.append([])
            continue
        rows.append(_row_spans(data, start, min(end, len(data))))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = img.load()
    for y, spans in enumerate(rows):
        for i, (x, width, src) in enumerate(spans):
            if i + 1 < len(spans):
                nxt = spans[i + 1][2]
            elif y + 1 < h and rows[y + 1]:
                nxt = rows[y + 1][0][2]
            else:
                nxt = len(data)
            count = nxt - src
            if count <= 0:
                count = max(int(width), 0)
            if count > w:
                count = w
            x0 = int(x)
            if x0 + count > w:
                x0 = 0 if count <= w else max(0, w - count)
            for k in range(count):
                if src + k >= len(data):
                    break
                idx = data[src + k]
                if idx == 0:
                    continue
                r, g, b = palette[idx]
                pix[x0 + k, y] = (r, g, b, 255)
    return pick_front(img, frames) if front else img


def decode_shp(path: Path) -> Image.Image | None:
    return decode_shp_bytes(path.read_bytes())


def _opaque_top(cell: Image.Image) -> int:
    w, h = cell.size
    pix = cell.load()
    lim = max(1, h * 2 // 5)
    n = 0
    for y in range(lim):
        for x in range(w):
            if pix[x, y][3] > 0:
                n += 1
    return n


def pick_front(img: Image.Image, frames: int) -> Image.Image:
    """Prefer the camera-facing cell on a direction strip."""
    w, h = img.size
    if w >= h * 3 and (frames >= 4 or w >= h * 3.5):
        cols = 4 if w >= h * 3.5 else max(2, w // max(h, 1))
        fw = w // cols
        if fw < 8:
            return img
        best_i, best = 0, -1
        for i in range(cols):
            score = _opaque_top(img.crop((i * fw, 0, (i + 1) * fw, h)))
            if score > best:
                best, best_i = score, i
        return img.crop((best_i * fw, 0, (best_i + 1) * fw, h))
    if h >= w * 3 and (frames >= 4 or h >= w * 3.5):
        rows = 4 if h >= w * 3.5 else max(2, h // max(w, 1))
        fh = h // rows
        if fh < 8:
            return img
        best_i, best = 0, -1
        for i in range(rows):
            score = _opaque_top(img.crop((0, i * fh, w, (i + 1) * fh)))
            if score > best:
                best, best_i = score, i
        return img.crop((0, best_i * fh, w, (best_i + 1) * fh))
    return img


def collect_item_shps(extract: Path) -> dict[str, Path]:
    latest: dict[str, Path] = {}
    for pak in PAK_ORDER:
        folder = extract / pak / "shape" / "item"
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if path.suffix.lower() == ".shp" and path.stem.lower().startswith("i"):
                latest[path.stem.lower()] = path
    return latest


def convert_all(extract: Path, dests: list[Path]) -> dict[str, str]:
    """Write PNGs named i0001.png. Returns stem -> filename."""
    files = collect_item_shps(extract)
    written: dict[str, str] = {}
    for dest in dests:
        dest.mkdir(parents=True, exist_ok=True)
    for stem, src in files.items():
        img = decode_shp(src)
        if img is None:
            continue
        name = f"{stem}.png"
        for dest in dests:
            img.save(dest / name, optimize=True)
        written[stem] = name
    return written
