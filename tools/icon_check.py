"""Check item-icon decodes, the PNGs on disk, and icons the wiki cannot show.

The contact sheet is rebuilt from the client extract (AO_EXTRACT). This script
does not fetch pictures from a website.
"""
from __future__ import annotations

import json
import re
import struct
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

from build_item_wiki import EXTRACT, load_icon_files
from shp_icon import PAK_ORDER, collect_item_shps, decode_shp_bytes, palette_span, rgb565

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "items.html"
ICON_DIR = ROOT / "docs" / "icons"
OUT_DIR = ROOT / "docs" / "icon-check"
SAMPLES = ("i0001", "i0100", "i0516", "i2171")
RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F


def rgb555(c: int) -> tuple[int, int, int]:
    r = ((c >> 10) & 31) * 255 // 31
    g = ((c >> 5) & 31) * 255 // 31
    b = (c & 31) * 255 // 31
    return r, g, b


def make_tlhs(width: int, height: int, runs: list[list[tuple[int, int, int]]],
              pixels: bytes, colours: list[int], pal_size: int, pad: bytes = b"",
              depth: int = 0, bpp: int = 1) -> bytes:
    """Build one TLHS icon. Each run is (x, width, extra bytes after its pixels)."""
    span_len = sum(8 * len(row) for row in runs)
    pal_off = 80 + height * 4 + span_len
    pal_bytes = b"".join(struct.pack("<H", word) for word in colours)
    px_off = pal_off + len(pal_bytes) + len(pad)
    spans = bytearray()
    row_off = []
    cursor = 0
    for row in runs:
        row_off.append(80 + height * 4 + len(spans))
        for x, run_width, extra in row:
            spans += struct.pack("<hhI", x, run_width, px_off + cursor)
            cursor += run_width * bpp + extra
    if len(pixels) < cursor:
        pixels += bytes(cursor - len(pixels))
    header = bytearray(80)
    header[0:4] = b"TLHS"
    struct.pack_into("<IIIII", header, 8, 1, pal_size, depth, width, height)
    struct.pack_into("<I", header, 44, px_off)
    struct.pack_into("<I", header, 64, pal_off)
    offsets = b"".join(struct.pack("<I", off) for off in row_off)
    return bytes(header) + offsets + bytes(spans) + pal_bytes + pad + pixels


def assert_pixels(img: Image.Image, expected: dict[tuple[int, int], tuple[int, int, int, int]], label: str) -> None:
    for (x, y), colour in expected.items():
        got = img.getpixel((x, y))
        if got != colour:
            raise SystemExit(f"{label}: pixel {x},{y} is {got}, expected {colour}")


def check_decoder_rules() -> None:
    """The two span bugs, plus RGB565 against colours the header says are in the table."""
    wide = make_tlhs(
        8, 1,
        [[(2, 2, 4)]],
        bytes([1, 1, 2, 2, 2, 2]),
        [0x0000, RED, BLUE],
        pal_size=3,
    )
    img = decode_shp_bytes(wide, front=False)
    assert img is not None
    assert_pixels(img, {
        (2, 0): (255, 0, 0, 255),
        (3, 0): (255, 0, 0, 255),
        (4, 0): (0, 0, 0, 0),
        (1, 0): (0, 0, 0, 0),
    }, "width field")

    clipped = make_tlhs(
        4, 1,
        [[(2, 4, 0)]],
        bytes([1, 1, 1, 1]),
        [0x0000, RED],
        pal_size=2,
    )
    img = decode_shp_bytes(clipped, front=False)
    assert img is not None
    assert_pixels(img, {
        (0, 0): (0, 0, 0, 0),
        (1, 0): (0, 0, 0, 0),
        (2, 0): (255, 0, 0, 255),
        (3, 0): (255, 0, 0, 255),
    }, "clip at the right edge")

    left = make_tlhs(
        4, 1,
        [[(-1, 2, 0)]],
        bytes([2, 1]),
        [0x0000, RED, BLUE],
        pal_size=3,
    )
    img = decode_shp_bytes(left, front=False)
    assert img is not None
    assert_pixels(img, {
        (0, 0): (255, 0, 0, 255),
        (1, 0): (0, 0, 0, 0),
    }, "clip at the left edge")

    # One real colour, then two pad bytes that are a red RGB565 word.
    # Reading past the header size would turn index 1 red.
    stopped = make_tlhs(
        1, 1,
        [[(0, 1, 0)]],
        bytes([1]),
        [0x0000],
        pal_size=1,
        pad=b"\x00\xf8",
    )
    img = decode_shp_bytes(stopped, front=False)
    assert img is not None and img.getpixel((0, 0)) == (0, 0, 0, 255), "palette ran into the pad"

    if rgb565(RED) != (255, 0, 0) or rgb565(GREEN) != (0, 255, 0) or rgb565(BLUE) != (0, 0, 255):
        raise SystemExit("RGB565 expansion is wrong")
    if rgb555(GREEN) == (0, 255, 0):
        raise SystemExit("the green test word is not distinct from RGB555")

    # Depth 16: each pixel is one RGB565 word. A zero word is a hole, and the
    # next byte is the next pixel's low byte, not a second palette index.
    direct = make_tlhs(
        4, 1,
        [[(0, 3, 0)]],
        struct.pack("<HHH", 0x0000, RED, BLUE),
        [],
        pal_size=0,
        depth=16,
        bpp=2,
    )
    img = decode_shp_bytes(direct, front=False)
    assert img is not None
    assert_pixels(img, {
        (0, 0): (0, 0, 0, 0),
        (1, 0): (255, 0, 0, 255),
        (2, 0): (0, 0, 255, 255),
        (3, 0): (0, 0, 0, 0),
    }, "rgb565 direct")

    clipped16 = make_tlhs(
        3, 1,
        [[(-1, 2, 0)]],
        struct.pack("<HH", GREEN, RED),
        [],
        pal_size=0,
        depth=16,
        bpp=2,
    )
    img = decode_shp_bytes(clipped16, front=False)
    assert img is not None
    assert_pixels(img, {
        (0, 0): (255, 0, 0, 255),
        (1, 0): (0, 0, 0, 0),
    }, "rgb565 left edge")

    # No colour count and no palette bytes is the same direct format.
    bare = make_tlhs(
        2, 1,
        [[(0, 2, 0)]],
        struct.pack("<HH", 0x0000, GREEN),
        [],
        pal_size=0,
        depth=0,
        bpp=2,
    )
    img = decode_shp_bytes(bare, front=False)
    assert img is not None and img.getpixel((0, 0)) == (0, 0, 0, 0)
    assert img.getpixel((1, 0)) == (0, 255, 0, 255), "zero colour count with an empty palette"

    # A zero colour count that still has palette bytes stays indexed.
    kept = make_tlhs(
        1, 1,
        [[(0, 1, 0)]],
        bytes([1]),
        [0x0000, RED],
        pal_size=0,
        depth=0,
    )
    img = decode_shp_bytes(kept, front=False)
    assert img is not None and img.getpixel((0, 0)) == (255, 0, 0, 255), "palette gap stays indexed"

    unknown = make_tlhs(
        1, 1,
        [[(0, 1, 0)]],
        bytes([1]),
        [0x0000, RED],
        pal_size=2,
        depth=24,
    )
    if decode_shp_bytes(unknown, front=False, source="i0343.shp") is not None:
        raise SystemExit("unknown depth was decoded")
    print("decoder rules ok: run width, edge clip, palette end, RGB565, 16-bit icons")


def load_page() -> tuple[dict[str, str], list[dict]]:
    html = PAGE.read_text(encoding="utf-8")
    files_m = re.search(r"const FILES = (\{.*?\});\n", html)
    data_m = re.search(r"const DATA = (\[.*?\]);\n", html)
    if not files_m or not data_m:
        raise SystemExit(f"could not find FILES and DATA in {PAGE}")
    files = json.loads(files_m.group(1))
    data = json.loads(data_m.group(1))
    return files, data


def stem_name(mapped: str) -> str:
    name = Path(str(mapped).replace("\\", "/")).name
    return Path(name).stem.lower()


def png_names() -> set[str]:
    if not ICON_DIR.is_dir():
        return set()
    return {path.name.lower() for path in ICON_DIR.glob("*.png")}


def resolves(icon_id: int, stem: str, names: set[str]) -> bool:
    if icon_id and f"{icon_id}.png" in names:
        return True
    return bool(stem and f"{stem}.png" in names)


def alpha_kind(path: Path) -> str:
    with Image.open(path) as img:
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        lo, hi = img.getchannel("A").getextrema()
    if hi == 0:
        return "blank"
    if lo == 255:
        return "opaque"
    return "ok"


def count_pngs(names: list[Path]) -> Counter:
    counts: Counter = Counter()
    for path in names:
        counts[alpha_kind(path)] += 1
    return counts


def index_shapes(extract: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    if not extract.is_dir():
        return found
    seen: set[str] = set()
    paks = []
    for name in PAK_ORDER:
        folder = extract / name
        if folder.is_dir():
            seen.add(folder.name.lower())
            paks.append(folder)
    for child in sorted(extract.iterdir()):
        if child.is_dir() and child.name.lower() not in seen and (child / "shape").is_dir():
            paks.append(child)
    for pak in paks:
        shape = pak / "shape"
        if not shape.is_dir():
            continue
        for folder in shape.iterdir():
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                if path.suffix.lower() != ".shp":
                    continue
                key = path.stem.lower()
                rel = f"{pak.name}/shape/{folder.name}/{path.name}"
                found.setdefault(key, []).append(rel)
    return found


def shape_hits(stem: str, shapes: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    item, other = [], []
    for rel in shapes.get(stem, []):
        if "/shape/item/" in rel.replace("\\", "/").lower():
            item.append(rel)
        else:
            other.append(rel)
    return item, other


def contact_sheet(shps: dict[str, Path]) -> None:
    scale = 4
    cells = []
    notes = []
    for stem in SAMPLES:
        path = shps.get(stem)
        if path is None:
            cells.append(None)
            notes.append(f"{stem}: SHP not in any pack under shape/item")
            continue
        data = path.read_bytes()
        frames, pal_size, _flag, w, h = struct.unpack_from("<IIIII", data, 8)
        px_off = struct.unpack_from("<I", data, 44)[0]
        pal_off = struct.unpack_from("<I", data, 64)[0]
        start, end, why = palette_span(data, pal_off, px_off, pal_size)
        n = max(0, (end - start) // 2)
        words = []
        for i in range(min(n, 8)):
            word = struct.unpack_from("<H", data, start + i * 2)[0]
            if word:
                words.append((i, word))
        colour_bits = ", ".join(
            f"[{i}] 0x{word:04X} rgb565={rgb565(word)} rgb555={rgb555(word)}"
            for i, word in words[:4]
        ) or "no non-zero colours in the first 8 entries"
        notes.append(
            f"{stem}: {w}x{h} frames={frames} pal_size={pal_size} "
            f"palette {start}..{end} ({n} colours, {why}); {colour_bits}"
        )
        cells.append(decode_shp_bytes(data))
    cell = 48 * scale
    pad = 12
    label_h = 22
    sheet = Image.new("RGBA", (pad + len(SAMPLES) * (cell + pad), pad + cell + label_h + pad), (16, 12, 28, 255))
    draw = ImageDraw.Draw(sheet)
    for i, img in enumerate(cells):
        x = pad + i * (cell + pad)
        y = pad
        if img is None:
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), outline=(228, 195, 106, 255))
            draw.text((x + 8, y + cell // 2), "missing", fill=(228, 195, 106, 255))
        else:
            shown = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
            ox = x + max(0, (cell - shown.width) // 2)
            oy = y + max(0, (cell - shown.height) // 2)
            sheet.paste(shown, (ox, oy), shown)
        draw.text((x, pad + cell + 4), SAMPLES[i], fill=(243, 226, 176, 255))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / "contact.png"
    sheet.save(dest)
    print(f"contact sheet {dest}")
    for line in notes:
        print(" ", line)


def main() -> None:
    check_decoder_rules()
    names = png_names()
    i_pngs = sorted(ICON_DIR.glob("i*.png")) if ICON_DIR.is_dir() else []
    numeric = sorted(p for p in ICON_DIR.glob("*.png") if p.stem.isdigit()) if ICON_DIR.is_dir() else []
    counts = count_pngs(i_pngs)
    print(
        f"i####.png on disk: {len(i_pngs)}  blank {counts['blank']}  "
        f"fully opaque {counts['opaque']}  with transparency {counts['ok']}"
    )
    print(f"numeric-named pngs in docs/icons: {len(numeric)}")

    print(f"extract: {EXTRACT} ({'found' if EXTRACT.exists() else 'not on this machine'})")
    shps = collect_item_shps(EXTRACT) if EXTRACT.exists() else {}
    if shps:
        decoded_blank = decoded_opaque = decoded_ok = decoded_fail = 0
        for stem, path in shps.items():
            img = decode_shp_bytes(path.read_bytes())
            if img is None:
                decoded_fail += 1
                continue
            lo, hi = img.getchannel("A").getextrema()
            if hi == 0:
                decoded_blank += 1
            elif lo == 255:
                decoded_opaque += 1
            else:
                decoded_ok += 1
        print(
            f"re-decoded shape/item: {len(shps)}  blank {decoded_blank}  "
            f"fully opaque {decoded_opaque}  with transparency {decoded_ok}  failed {decoded_fail}"
        )
        contact_sheet(shps)
    else:
        print("contact sheet skipped: no shape/item SHP files in the extract")

    files, data = load_page()
    xml_map = {str(k): v for k, v in load_icon_files().items()} if EXTRACT.exists() else {}
    shapes = index_shapes(EXTRACT) if EXTRACT.exists() else {}
    missing = []
    no_icon = 0
    for item in data:
        icon = int(item.get("icon") or 0)
        if not icon:
            no_icon += 1
            continue
        baked = files.get(str(icon), "")
        stem = stem_name(baked) if baked else ""
        if resolves(icon, stem, names):
            continue
        xml = xml_map.get(str(icon), "")
        xml_stem = stem_name(xml) if xml else ""
        look = stem or xml_stem
        tried = []
        if look:
            tried.append(look)
        else:
            tried.extend([f"i{icon}", f"i{icon:04d}"])
        item_hits, other_hits = [], []
        for candidate in tried:
            item_hits, other_hits = shape_hits(candidate, shapes)
            if item_hits or other_hits:
                break
        id_stem = ", ".join(tried) if not look else ""
        missing.append((item.get("id"), item.get("name", ""), icon, baked or "-", xml or "-", item_hits, other_hits, id_stem))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = OUT_DIR / "missing.txt"
    mapped = shp_item = shp_other = shp_none = xml_hit = 0
    lines = []
    for iid, name, icon, baked, xml, item_hits, other_hits, id_stem in missing:
        if baked != "-":
            mapped += 1
        if xml != "-":
            xml_hit += 1
        if item_hits:
            shp_item += 1
            where = "shape/item " + item_hits[0]
        elif other_hits:
            shp_other += 1
            where = "other shape " + other_hits[0]
        else:
            shp_none += 1
            where = "no SHP" if EXTRACT.exists() else "extract not available"
        extra = f" also tried {id_stem}.SHP" if id_stem else ""
        lines.append(f"item {iid}\t{name}\ticon {icon}\tpage-map {baked}\txml {xml}\t{where}{extra}")
    report.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"items in DATA: {len(data)}")
    print(f"items with no interface id: {no_icon}")
    print(f"items whose icon resolves to no PNG: {len(missing)}  (list: {report})")
    print(f"  of those, page icon map has a stem: {mapped}")
    print(f"  itemicon xml has the id: {xml_hit}" + ("" if EXTRACT.exists() else " (xml not read; extract missing)"))
    print(f"  SHP in shape/item: {shp_item}")
    print(f"  SHP in another shape folder: {shp_other}")
    print(f"  SHP not found: {shp_none}")
    by_icon = Counter(row[2] for row in missing)
    print(f"  distinct missing interface ids: {len(by_icon)}")


if __name__ == "__main__":
    main()
