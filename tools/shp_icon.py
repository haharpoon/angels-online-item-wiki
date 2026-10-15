"""Decode Midage TLHS item icons (shape/item/i####.SHP) to PNG.

Last-pak-wins, same order as extract_content.py. Multi-direction sheets
keep the cell with the most pixels in the upper half (facing the camera);
the in-game default is often the back view.

A palette size of 512 and a palette offset of 0 means there is no palette:
each pixel is a little-endian RGB565 word, and nothing inside a span is
keyed out. Every other TLHS icon is 8-bit, with index 0 transparent.
The flag at offset 16 is not a bit depth.

Each row record is int16 pixel count, then int16 x, then uint32 source
offset. A record of (0, -1) ends the row.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image

PAK_ORDER = (
    ["data1", "update", "update2", "update3"]
    + [f"UPDATE{i}" for i in range(4, 22)]
    + [f"update{i}" for i in range(22, 27)]
)


def rgb565(c: int) -> tuple[int, int, int]:
    """Expand one little-endian RGB565 colour. Green uses 6 bits, so this is not RGB555."""
    r = ((c >> 11) & 31) * 255 // 31
    g = ((c >> 5) & 63) * 255 // 63
    b = (c & 31) * 255 // 31
    return r, g, b


def _row_spans(data: bytes, start: int, end: int) -> list[tuple[int, int, int]]:
    """Read runs as (x, pixel count, src).

    On disk the first int16 is the pixel count and the second is x.
    (0, -1, cumulative byte count) ends the row.
    """
    spans = []
    p = start
    while p + 8 <= end and p + 8 <= len(data):
        count, x = struct.unpack_from("<hh", data, p)
        src = struct.unpack_from("<I", data, p + 4)[0]
        p += 8
        if count == 0 and x == -1:
            break
        spans.append((x, count, src))
    return spans


def palette_span(data: bytes, pal_off: int, px_off: int, pal_size: int) -> tuple[int, int, str]:
    """Where the RGB565 table ends.

    Colours are 16-bit and sit before the pixel bytes. The header size is
    trusted when it is a colour count or an even byte length that fits in
    that gap. Otherwise the table stops at the pixel block so index bytes
    are not read as colours.
    """
    if pal_off < 0 or pal_off >= len(data):
        return pal_off, pal_off, "palette offset is outside the file"
    hard = len(data)
    if px_off > pal_off:
        hard = px_off
        gap = px_off - pal_off
        if 0 < pal_size <= 256 and pal_size * 2 == gap:
            return pal_off, px_off, "header colour count fills the gap before the pixels"
        if 0 < pal_size <= 512 and pal_size % 2 == 0 and pal_size == gap:
            return pal_off, px_off, "header byte length fills the gap before the pixels"
        if 0 < pal_size <= 256 and pal_size * 2 < gap:
            return pal_off, pal_off + pal_size * 2, "header colour count; bytes after it and before the pixels are not colours"
        if 0 < pal_size <= 512 and pal_size % 2 == 0 and pal_size < gap:
            return pal_off, pal_off + pal_size, "header byte length; bytes after it and before the pixels are not colours"
        return pal_off, px_off, "pixel block starts here; header size does not match the gap"
    if 0 < pal_size <= 256 and pal_off + pal_size * 2 <= len(data):
        return pal_off, pal_off + pal_size * 2, "header colour count"
    if 0 < pal_size <= 512 and pal_size % 2 == 0 and pal_off + pal_size <= len(data):
        return pal_off, pal_off + pal_size, "header byte length"
    return pal_off, min(len(data), pal_off + 512), "no pixel offset; capped at 256 colours"


INDEX8 = "index8"
RGB565 = "rgb565"


def header_fields(data: bytes) -> dict | None:
    """The TLHS fields that choose the pixel format. None when it is not TLHS."""
    if len(data) < 80 or data[:4] != b"TLHS":
        return None
    frames, pal_size, flag, width, height = struct.unpack_from("<IIIII", data, 8)
    return {
        "version": struct.unpack_from("<I", data, 4)[0],
        "frames": frames,
        "pal_size": pal_size,
        "flag": flag,
        "width": width,
        "height": height,
        "px_off": struct.unpack_from("<I", data, 44)[0],
        "pal_off": struct.unpack_from("<I", data, 64)[0],
    }


def icon_format(fields: dict) -> str:
    """index8 or rgb565. The flag field does not select the format.

    Palette size 512 and palette offset 0 means the pixel block is
    little-endian RGB565 and there is no colour key. Anything else is an
    8-bit index into the RGB565 palette, where index 0 is transparent.
    """
    if int(fields["pal_size"]) == 512 and int(fields["pal_off"]) == 0:
        return RGB565
    return INDEX8


def decode_shp_bytes(
    data: bytes,
    front: bool = True,
    fmt: str | None = None,
    source: str = "",
) -> Image.Image | None:
    fields = header_fields(data)
    if fields is None:
        return None
    frames = int(fields["frames"])
    pal_size = int(fields["pal_size"])
    w = int(fields["width"])
    h = int(fields["height"])
    px_off = int(fields["px_off"])
    pal_off = int(fields["pal_off"])
    detected = icon_format(fields)
    if fmt is None:
        fmt = detected
    if fmt not in (INDEX8, RGB565):
        where = source or "icon"
        print(
            f"warning: {where}: unknown icon pixel format "
            f"pal_size={pal_size} pal_off={pal_off}",
            file=sys.stderr,
        )
        return None
    if w <= 0 or h <= 0 or w > 512 or h > 512:
        return None
    if 80 + h * 4 > len(data):
        return None
    if fmt == INDEX8 and (pal_off >= len(data) or pal_off < 0):
        return None
    stride = 2 if fmt == RGB565 else 1
    palette = [(0, 0, 0)] * 256
    if fmt == INDEX8:
        pal_start, pal_end, _why = palette_span(data, pal_off, px_off, pal_size)
        n = min(256, max(0, (pal_end - pal_start) // 2))
        for i in range(n):
            palette[i] = rgb565(struct.unpack_from("<H", data, pal_start + i * 2)[0])

    table_end = 80 + h * 4
    if fmt == RGB565 and pal_off <= table_end:
        span_limit = px_off if px_off > table_end else len(data)
    else:
        span_limit = pal_off
    offs = [struct.unpack_from("<I", data, 80 + i * 4)[0] for i in range(h)]
    rows = []
    for y in range(h):
        start = offs[y]
        end = offs[y + 1] if y + 1 < h else span_limit
        if start < 0 or start > len(data):
            rows.append([])
            continue
        rows.append(_row_spans(data, start, min(end, len(data))))

    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = img.load()
    for _y, spans in enumerate(rows):
        for x, width, src in spans:
            # The run's own width is the pixel count. The gap until the next
            # src includes padding and would paint the row too wide.
            count = int(width)
            src_i = int(src)
            x0 = int(x)
            if count <= 0 or src_i < 0:
                continue
            if x0 < 0:
                src_i += (-x0) * stride
                count += x0
                x0 = 0
            if x0 >= w or count <= 0:
                continue
            # Keep the run where it started. Drop the pixels that fall off the edge.
            if x0 + count > w:
                count = w - x0
            if src_i >= len(data):
                continue
            byte_count = count * stride
            if src_i + byte_count > len(data):
                count = (len(data) - src_i) // stride
            for k in range(count):
                if fmt == RGB565:
                    # No colour key. 0x0000 is black, and 0xFFFE/0xFFFF are white.
                    word = struct.unpack_from("<H", data, src_i + k * 2)[0]
                    r, g, b = rgb565(word)
                else:
                    idx = data[src_i + k]
                    if idx == 0:
                        continue
                    r, g, b = palette[idx]
                pix[x0 + k, _y] = (r, g, b, 255)
    return pick_front(img, frames) if front else img


def decode_shp(path: Path) -> Image.Image | None:
    return decode_shp_bytes(path.read_bytes(), source=path.name)


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
    counts = {INDEX8: 0, RGB565: 0, "unknown": 0, "failed": 0}
    for dest in dests:
        dest.mkdir(parents=True, exist_ok=True)
    for stem, src in files.items():
        data = src.read_bytes()
        fields = header_fields(data)
        kind = icon_format(fields) if fields else None
        if kind is None:
            counts["unknown"] += 1
        else:
            counts[kind] += 1
        img = decode_shp_bytes(data, source=src.name)
        if img is None:
            if kind is not None:
                counts["failed"] += 1
            continue
        name = f"{stem}.png"
        for dest in dests:
            img.save(dest / name, optimize=True)
        written[stem] = name
    print(
        f"icons: {counts[INDEX8]} palette, {counts[RGB565]} rgb565, "
        f"{counts['unknown']} unknown format, {counts['failed']} not written"
    )
    return written


def debug_shp(path: Path, out: Path | None = None) -> None:
    """Print one icon's header and write the chosen decode plus both formats."""
    data = path.read_bytes()
    fields = header_fields(data)
    if fields is None:
        print(f"{path}: not a TLHS icon")
        return
    kind = icon_format(fields)
    print(f"{path}")
    print(
        f"  version={fields['version']} frames={fields['frames']} "
        f"pal_size={fields['pal_size']} flag={fields['flag']} "
        f"size={fields['width']}x{fields['height']}"
    )
    print(f"  pixel offset={fields['px_off']} palette offset={fields['pal_off']}")
    if kind == RGB565:
        print("  format: rgb565, 2 bytes per pixel, no colour key")
    elif kind == INDEX8:
        print("  format: 8-bit palette index, index 0 is transparent")
    else:
        print("  format: unknown. Not written by convert_all. Both previews are still saved here.")
    folder = out.parent if out else path.parent
    folder.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    chosen = folder / (out.name if out else f"{stem}.debug.png")
    img = decode_shp_bytes(data, fmt=kind, source=path.name) if kind else None
    if img is not None:
        img.save(chosen)
        print(f"  wrote {chosen}")
    for forced, suffix in ((INDEX8, "index8"), (RGB565, "rgb565")):
        preview = decode_shp_bytes(data, fmt=forced, source=path.name)
        dest = folder / f"{stem}.{suffix}.png"
        if preview is None:
            print(f"  {suffix}: could not decode")
            continue
        preview.save(dest)
        print(f"  wrote {dest}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect one TLHS item icon.")
    parser.add_argument("shp", type=Path, help="Path to one .shp, for example i0343.shp")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print the header and write index8 and rgb565 previews.",
    )
    parser.add_argument("--out", type=Path, help="Where to write the chosen decode.")
    args = parser.parse_args()
    if not args.shp.is_file():
        raise SystemExit(f"no such file: {args.shp}")
    if args.debug or args.out:
        debug_shp(args.shp, args.out)
        return
    img = decode_shp(args.shp)
    if img is None:
        raise SystemExit(f"could not decode {args.shp}")
    dest = args.shp.with_suffix(".png")
    img.save(dest)
    print(dest)


if __name__ == "__main__":
    main()
