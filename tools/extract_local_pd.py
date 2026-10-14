"""Extract local Wait.spr atlases using CHARDEF.XML + char*.obd."""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from client_pd_map import find_spr, load_ride_rows, parse_obd, ride_by_appearance
from ewsp import decode_wait, pack_atlas
from translate_text import translate_catalog_display_text

# The wiki dummy is the classic ~82px body. Later packs also ship a taller
# Wait.spr (12xxxx) in the same folder; that one floats above this body.
CLASSIC_BODY = 82
EXPECTED_FRAMES = 15

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "corpus" / "content.db"
PD_DIR = ROOT / "docs" / "pd"
SPRITE_DIR = PD_DIR / "sprites"
SHARE_SPRITE = ROOT / "share" / "items" / "pd" / "sprites"
CATALOG = PD_DIR / "client_pd_preview.json"
CATALOG_JS = PD_DIR / "catalog.js"
SHARE_CATALOG = ROOT / "share" / "items" / "pd" / "client_pd_preview.json"
SHARE_JS = ROOT / "share" / "items" / "pd" / "catalog.js"
SPRITE_DIRS = (SPRITE_DIR, SHARE_SPRITE)

SLOT_COLS = (
    ("頭部", "head"),
    ("身體", "body"),
    ("手部", "hands"),
    ("腳部", "feet"),
    ("背部", "back"),
    ("主手", "main"),
    ("副手", "off"),
)
WEAR_TYPES = {
    "紙娃娃", "座騎",
    "劍", "刀", "斧", "錘", "槍", "杖", "弓箭", "彈弓", "影刃", "盾",
    "衣服", "頭飾", "手套", "鞋子", "披風", "飾品", "背包",
}
ITEM_TABLES = ("item", "item2", "item3", "item4", "item5", "item6", "item7", "item8", "item9")
# English ids already used by the wiki catalog filter. Unknown labels stay raw.
COLLECTION_IDS = {
    "繽紛職業": "careers",
    "各國風情": "international",
    "特殊其他": "special",
    "可愛動物": "cute-animals",
    "歡樂節慶": "festive",
}
YES = "是"


def _int(val) -> int | None:
    try:
        n = int(float(val))
    except (TypeError, ValueError):
        return None
    return n if n else None


def _yes(val) -> bool:
    return str(val or "").strip() == YES


def _table_cols(con: sqlite3.Connection, table: str) -> set[str]:
    return {c[1] for c in con.execute(f"pragma table_info({table})")}


def audit_source_flags(db: Path = DB) -> None:
    """Print which doll/item columns can actually drive flags. Does not guess."""
    con = sqlite3.connect(db)
    tables = ["doll", *ITEM_TABLES]
    present = [t for t in tables if con.execute(
        "select 1 from sqlite_master where type='table' and name=?", (t,)
    ).fetchone()]
    two_hand = []
    for table in present:
        cols = _table_cols(con, table)
        hit = [c for c in cols if "雙" in c or "two" in c.lower()]
        if hit:
            two_hand.extend(f"{table}.{c}" for c in hit)
    if two_hand:
        print(f"twoHanded columns: {', '.join(two_hand)}")
    else:
        print(
            f"warning: twoHanded left False; no two-handed column in "
            f"{len(present)} tables ({', '.join(present)})"
        )
    doll_cols = _table_cols(con, "doll") if "doll" in present else set()
    for col, flag in (("身體袍", "robe"), ("背部另一層", "capeLayer"), ("收藏類別", "collection")):
        if col not in doll_cols:
            print(f"warning: doll.{col} missing; {flag} left default")
            continue
        counts = Counter(r[0] for r in con.execute(f'select "{col}" from doll'))
        print(f"doll.{col} -> {flag}: {dict(counts)}")
    flex = 0
    right_only = 0
    left_only = 0
    hand_tables = 0
    for table in ITEM_TABLES:
        if table not in present:
            continue
        cols = _table_cols(con, table)
        if "右手裝備" not in cols or "左手裝備" not in cols:
            print(f"warning: {table} has no 右手裝備/左手裝備; flexibleHands unknown on that table")
            continue
        hand_tables += 1
        for right, left in con.execute('select "右手裝備", "左手裝備" from ' + table):
            r, l = _yes(right), _yes(left)
            if r and l:
                flex += 1
            elif r:
                right_only += 1
            elif l:
                left_only += 1
    print(
        f"flexibleHands from 右手裝備+左手裝備 on {hand_tables} item tables: "
        f"{flex} both, {right_only} right only, {left_only} left only"
    )


def load_dolls(db: Path) -> dict[int, dict]:
    con = sqlite3.connect(db)
    cols = _table_cols(con, "doll")
    dolls = {}
    fields = [c for c, _ in SLOT_COLS if c in cols]
    extra_names = [c for c in ("頭部全罩", "頭部半罩", "身體袍", "背部另一層", "收藏類別") if c in cols]
    for col, flag in (("身體袍", "robe"), ("背部另一層", "capeLayer"), ("收藏類別", "collection")):
        if col not in cols:
            print(f"warning: doll.{col} missing; {flag} left default")
    q = "select id," + ",".join(f'"{c}"' for c in fields + extra_names) + " from doll"
    for row in con.execute(q):
        did = _int(row[0])
        if did is None:
            continue
        parts = {}
        for name, val in zip(fields, row[1:1 + len(fields)]):
            n = _int(val)
            if n:
                parts[dict(SLOT_COLS)[name]] = n
        if not parts:
            continue
        extra_vals = dict(zip(extra_names, row[1 + len(fields):]))
        cover = "full" if _int(extra_vals.get("頭部全罩")) else (
            "half" if _int(extra_vals.get("頭部半罩")) else "none"
        )
        raw_collection = extra_vals.get("收藏類別")
        raw_collection = str(raw_collection).strip() if raw_collection else ""
        dolls[did] = {
            "parts": parts,
            "headCover": cover,
            "robe": _yes(extra_vals.get("身體袍")) if "身體袍" in cols else False,
            "capeLayer": _yes(extra_vals.get("背部另一層")) if "背部另一層" in cols else False,
            "collection": COLLECTION_IDS.get(raw_collection, raw_collection or None),
            "collectionRaw": raw_collection or None,
        }
    return dolls


def load_items(db: Path) -> list[dict]:
    con = sqlite3.connect(db)
    out = []
    for table in ITEM_TABLES:
        if not con.execute(
            "select 1 from sqlite_master where type='table' and name=?", (table,)
        ).fetchone():
            continue
        cols = _table_cols(con, table)
        if "id" not in cols or "原型外觀" not in cols or "物品類別" not in cols:
            continue
        name_sql = '"基本名稱"' if "基本名稱" in cols else (
            '"原型名稱"' if "原型名稱" in cols else "null"
        )
        hand_cols = [c for c in ("右手裝備", "左手裝備") if c in cols]
        if len(hand_cols) < 2:
            print(f"warning: {table} missing 右手裝備/左手裝備; flexibleHands left False for its rows")
        sel_extra = "".join(f', "{c}"' for c in hand_cols)
        sel = f'select "id", "原型外觀", "物品類別", {name_sql}{sel_extra} from {table}'
        try:
            rows = list(con.execute(sel))
        except sqlite3.OperationalError:
            continue
        for row in rows:
            iid, look, typ, name, *hands = row
            if typ not in WEAR_TYPES:
                continue
            item_id, appearance = _int(iid), _int(look)
            if item_id is None or appearance is None:
                continue
            rec = {"id": item_id, "look": appearance, "type": typ, "name": str(name or item_id)}
            if len(hand_cols) == 2:
                rec["right"] = _yes(hands[0])
                rec["left"] = _yes(hands[1])
                rec["flexible"] = rec["right"] and rec["left"]
            out.append(rec)
    return out


def skin_match(pd: dict) -> tuple[tuple[int, int, int], int]:
    """Reference colour and tolerance from customization.skinTones[0].

    Tone 0 is the identity swatch. Its tolerance is 0 in the shipped catalog,
    so a hit is an exact RGB match of that reference. Later tones reuse the
    same reference with a wider tolerance at paint time.
    """
    tones = ((pd.get("customization") or {}).get("skinTones") or [{}])
    tone = tones[0] if tones else {}
    ref = tone.get("reference") or [255, 202, 156]
    tol = int(tone.get("tolerance") or 0)
    return (int(ref[0]), int(ref[1]), int(ref[2])), tol


def count_skin_pixels(image: Image.Image, reference: tuple[int, int, int], tolerance: int) -> int:
    tol2 = tolerance * tolerance
    px = image.convert("RGBA").load()
    width, height = image.size
    hits = 0
    rr, gg, bb = reference
    for y in range(height):
        for x in range(width):
            r, g, b, a = px[x, y]
            if not a:
                continue
            dist = (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2
            if dist <= tol2:
                hits += 1
    return hits


def choose_tint(role: str, hits: int) -> str:
    """Wearable item atlases are skin. Rides and weapons stay none unless pixels match."""
    if role == "hair":
        return "hair"
    if role == "base":
        return "skin"
    if role in ("ride", "weapon"):
        return "skin" if hits else "none"
    return "skin"


def sprite_role(key: str, layers: set[str] | None = None) -> str:
    if key.startswith("hair"):
        return "hair"
    if key.startswith("base"):
        return "base"
    if key.startswith("ride"):
        return "ride"
    if layers and layers <= {"main", "off"}:
        return "weapon"
    return "wear"


def extract_sprite(
    path: Path,
    key: str,
    dests: list[Path],
    cache: dict,
    role: str,
    reference: tuple[int, int, int],
    tolerance: int,
) -> dict | None:
    if key in cache:
        return cache[key]
    frames = decode_wait(path)
    if not frames:
        return None
    atlas, meta, cell_w, cell_h = pack_atlas(frames)
    name = f"{key}.png"
    for dest in dests:
        dest.mkdir(parents=True, exist_ok=True)
        atlas.save(dest / name, optimize=True)
    hits = count_skin_pixels(atlas, reference, tolerance)
    rec = {
        "url": f"assets/pd-preview/sprites/{name}",
        "tint": choose_tint(role, hits),
        "width": atlas.size[0],
        "height": atlas.size[1],
        "cellWidth": cell_w,
        "cellHeight": cell_h,
        "frames": meta,
        "sourceAsset": str(path),
    }
    cache[key] = rec
    return rec


def ensure_sprite(
    path: Path,
    key: str,
    dests: list[Path],
    cache: dict,
    pd: dict,
    role: str,
    reference: tuple[int, int, int],
    tolerance: int,
) -> str | None:
    existing = pd["sprites"].get(key)
    if existing and (not existing.get("sourceAsset") or existing.get("sourceAsset") == str(path)):
        return key
    rec = extract_sprite(path, key, dests, cache, role, reference, tolerance)
    if not rec:
        return None
    pd["sprites"][key] = rec
    return key


_wait_choice: dict[str, Path] = {}


def classic_wait(path: Path | None) -> Path | None:
    """Prefer the Wait.spr that matches the classic paper-doll body."""
    if path is None:
        return None
    folder = str(path.parent)
    if folder in _wait_choice:
        return _wait_choice[folder]
    waits = [p for p in path.parent.iterdir() if p.suffix.lower() == ".spr" and "wait" in p.name.lower()]
    best, best_score = path, 10**9
    for cand in waits or [path]:
        frames = decode_wait(cand)
        if not frames:
            continue
        score = abs(frames[0]["height"] - CLASSIC_BODY)
        if score < best_score:
            best, best_score = cand, score
    _wait_choice[folder] = best
    return best


def resolve_item(comp: int, sex: str, obd_items: dict, hand: str = "main") -> tuple[str, Path, Path | None] | None:
    suf = "g" if sex == "female" else "b"
    if hand == "off":
        keys = ((comp, suf + "l"), (comp, suf), (comp, ""))
    else:
        keys = ((comp, suf), (comp, ""), (comp, suf + "l"))
    rec = None
    for key in keys:
        rec = obd_items.get(key)
        if rec:
            break
    if not rec:
        return None
    wait = classic_wait(find_spr(rec["folder"], rec["wait"]))
    if wait is None:
        return None
    sit = find_spr(rec["folder"], rec["sit"]) if rec.get("sit") else None
    suffix = suf + ("l" if hand == "off" else "")
    key_name = f"item-{comp}{suffix}"
    return key_name, wait, sit


def mounted_key(
    sit: Path | None,
    standing_key: str,
    dests: list[Path],
    cache: dict,
    pd: dict,
    role: str,
    reference: tuple[int, int, int],
    tolerance: int,
) -> str:
    """Use the sit atlas only when it decodes a full 15-frame sheet."""
    if sit is None:
        return standing_key
    frames = decode_wait(sit)
    count = 0 if not frames else len(frames)
    if count < EXPECTED_FRAMES:
        print(f"  mounted {sit} decoded {count} frames; using standing {standing_key}")
        return standing_key
    mkey = standing_key + "-mounted"
    if not ensure_sprite(sit, mkey, dests, cache, pd, role, reference, tolerance):
        print(f"  mounted {sit} did not pack; using standing {standing_key}")
        return standing_key
    return mkey


def layer_for(slot: str, flags: dict) -> str:
    if slot == "body" and flags.get("robe"):
        return "robe"
    if slot == "back" and flags.get("capeLayer"):
        return "cape"
    return slot


def placements_for(component_ids: dict, flags: dict) -> list[dict]:
    slots = [s for s in ("head", "body", "hands", "feet", "back", "main", "off") if s in component_ids]
    hand_only = bool(slots) and set(slots) <= {"main", "off"}
    if flags.get("twoHanded") and "main" in component_ids:
        return [{"id": "both", "occupies": ["main", "off"], "layers": ["main"]}]
    if flags.get("flexibleHands") and hand_only:
        return [
            {"id": "main", "occupies": ["main"], "layers": ["main"]},
            {"id": "off", "occupies": ["off"], "layers": ["off"]},
        ]
    layers = [layer_for(s, flags) for s in slots]
    return [{"id": "default", "occupies": slots, "layers": layers}]


def group_flexible(group: list[dict], mixed: list[int]) -> bool:
    """True when every item in the look-group can sit in either hand.

    Mixed groups are counted and left False. There is no two-handed column to
    promote a right-only weapon into twoHanded.
    """
    if not group or any("flexible" not in it for it in group):
        if any(it.get("flexible") for it in group):
            mixed.append(group[0]["look"])
        return False
    flags = [bool(it.get("flexible")) for it in group]
    if all(flags):
        return True
    if any(flags):
        mixed.append(group[0]["look"])
    return False


def referenced_sprite_keys(pd: dict) -> set[str]:
    refs: set[str] = set()
    custom = pd.get("customization") or {}
    for sex in (custom.get("sexes") or {}).values():
        refs.update(v for v in (sex.get("baseSprites") or {}).values() if isinstance(v, str))
        for hair in sex.get("hairstyles") or []:
            refs.update(v for v in (hair.get("sprites") or {}).values() if isinstance(v, str))
    for item in pd.get("items") or []:
        ride = item.get("ride") or {}
        if isinstance(ride.get("sprite"), str):
            refs.add(ride["sprite"])
        comps = item.get("components") or {}
        for sex in comps.values():
            if not isinstance(sex, dict):
                continue
            for pose in sex.values():
                if isinstance(pose, dict):
                    refs.update(v for v in pose.values() if isinstance(v, str))
    return refs


def layers_by_sprite(pd: dict) -> dict[str, set[str]]:
    found: dict[str, set[str]] = defaultdict(set)
    for item in pd.get("items") or []:
        for sex in (item.get("components") or {}).values():
            if not isinstance(sex, dict):
                continue
            for pose in sex.values():
                if not isinstance(pose, dict):
                    continue
                for layer, key in pose.items():
                    if isinstance(key, str):
                        found[key].add(layer)
    return found


def retint_null_sprites(pd: dict) -> Counter:
    reference, tolerance = skin_match(pd)
    print(f"skin match reference {list(reference)} tolerance {tolerance}")
    layers = layers_by_sprite(pd)
    counts: Counter = Counter()
    changed = 0
    for key, rec in pd["sprites"].items():
        if rec.get("tint") not in (None, ""):
            counts[rec.get("tint")] += 1
            continue
        role = sprite_role(key, layers.get(key))
        png = SPRITE_DIR / f"{key}.png"
        if not png.is_file():
            png = SHARE_SPRITE / f"{key}.png"
        hits = 0
        if png.is_file() and role in ("ride", "weapon"):
            with Image.open(png) as image:
                hits = count_skin_pixels(image, reference, tolerance)
        tint = choose_tint(role, hits)
        rec["tint"] = tint
        counts[tint] += 1
        changed += 1
    print(f"filled {changed} null tints; breakdown {dict(counts)}")
    return counts


def prune_unreferenced(pd: dict) -> tuple[int, int]:
    refs = referenced_sprite_keys(pd)
    stale = sorted(k for k in pd["sprites"] if k not in refs)
    print(f"unreferenced sprite records: {len(stale)}")
    pngs = []
    keep = set(pd["sprites"]) - set(stale)
    for folder in SPRITE_DIRS:
        if not folder.is_dir():
            continue
        for path in folder.glob("*.png"):
            if path.stem not in keep:
                pngs.append(path)
    print(f"unreferenced pngs: {len(pngs)}")
    for key in stale:
        del pd["sprites"][key]
    deleted = 0
    for path in pngs:
        if path.is_file() and path.parent in SPRITE_DIRS:
            path.unlink()
            deleted += 1
    print(f"deleted {deleted} pngs from docs/pd/sprites and share/items/pd/sprites")
    short = [
        key for key, rec in pd["sprites"].items()
        if key.endswith("-mounted") and len(rec.get("frames") or []) < EXPECTED_FRAMES
    ]
    print(f"mounted atlases with fewer than {EXPECTED_FRAMES} frames: {len(short)}")
    if short[:8]:
        print("  " + ", ".join(short[:8]))
    return len(stale), deleted


def write_tint_masks(pd: dict) -> None:
    """Write same-origin recolor layers so file:// Chrome can tint without reading the PNG.

    A folder open gives each file its own origin, so drawImage taints the canvas and
    getImageData throws. These masks ship inside a classic script instead.
    """
    import base64
    import io

    custom = pd.get("customization") or {}
    specs = {}
    for tint, key in (("skin", "skinTones"), ("hair", "hairColors")):
        tones = custom.get(key) or []
        if not tones:
            continue
        ref = tuple(int(v) for v in (tones[0].get("reference") or [0, 0, 0]))
        tol = max(int(tone.get("tolerance") or 0) for tone in tones)
        specs[tint] = (ref, tol * tol)
    masks = {}
    for key, rec in pd.get("sprites", {}).items():
        tint = rec.get("tint")
        if tint not in specs:
            continue
        png = SPRITE_DIR / f"{key}.png"
        if not png.is_file():
            png = SHARE_SPRITE / f"{key}.png"
        if not png.is_file():
            continue
        reference, tol2 = specs[tint]
        with Image.open(png) as image:
            rgba = image.convert("RGBA")
        px = rgba.load()
        width, height = rgba.size
        mask = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        out = mask.load()
        hits = 0
        rr, gg, bb = reference
        for y in range(height):
            for x in range(width):
                r, g, b, a = px[x, y]
                if not a:
                    continue
                if (r - rr) ** 2 + (g - gg) ** 2 + (b - bb) ** 2 <= tol2:
                    out[x, y] = (r, g, b, a)
                    hits += 1
        if not hits:
            continue
        buf = io.BytesIO()
        mask.save(buf, format="PNG", optimize=True)
        masks[key] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    text = "window.PD_TINT_MASKS=" + json.dumps(masks, separators=(",", ":")) + ";\n"
    for dest in (PD_DIR / "tint-masks.js", ROOT / "share" / "items" / "pd" / "tint-masks.js"):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    print(f"tint masks {len(masks)} ({len(text)} bytes)")


def dump_catalog(pd: dict) -> None:
    text = json.dumps(pd, ensure_ascii=False, separators=(",", ":"))
    js = "window.PD_CATALOG = " + text + ";\n"
    for dest in (CATALOG, SHARE_CATALOG):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
    for dest in (CATALOG_JS, SHARE_JS):
        dest.write_text(js, encoding="utf-8")


def write_catalog(pd: dict) -> None:
    translate_catalog_display_text(pd)
    dump_catalog(pd)


def retint_and_prune() -> None:
    print("loading catalog...")
    pd = json.loads(CATALOG.read_text(encoding="utf-8"))
    print(f"  {len(pd['items'])} items, {len(pd['sprites'])} sprites, local {sum(1 for i in pd['items'] if i.get('local'))}")
    audit_source_flags()
    prune_unreferenced(pd)
    retint_null_sprites(pd)
    write_tint_masks(pd)
    dump_catalog(pd)
    print(f"catalog {len(pd['items'])} records, {len(pd['sprites'])} sprites")
    print(f"wrote {CATALOG} ({CATALOG.stat().st_size} bytes)")


def main() -> None:
    print("loading catalog...")
    pd = json.loads(CATALOG.read_text(encoding="utf-8"))
    kept = [it for it in pd["items"] if not it.get("local")]
    wiki_ids = set()
    for it in kept:
        wiki_ids.add(it["item_id"])
        wiki_ids.update(it.get("itemIds") or [])
    pd["items"] = kept
    print(f"  kept {len(kept)} wiki records")
    audit_source_flags()

    print("loading CHARDEF + OBD...")
    ride_rows = load_ride_rows()
    obd_items, obd_rides = parse_obd()
    print(f"  {len(ride_rows)} CHARDEF rides, {len(obd_rides)} H objects, {len(obd_items)} I objects")

    dolls = load_dolls(DB)
    items = load_items(DB)
    dests = [SPRITE_DIR, SHARE_SPRITE]
    cache: dict[str, dict] = {}
    added = []
    new_sprites = 0
    reference, tolerance = skin_match(pd)
    print(f"skin match reference {list(reference)} tolerance {tolerance}")

    mounts = defaultdict(list)
    wears = defaultdict(list)
    for it in items:
        if it["id"] in wiki_ids:
            continue
        if it["type"] == "座騎":
            mounts[it["look"]].append(it)
        elif it["look"] in dolls:
            wears[it["look"]].append(it)

    print(f"  local mount groups {len(mounts)}, wear groups {len(wears)}")

    for look, group in mounts.items():
        row = ride_by_appearance(ride_rows, look)
        if not row or row["layer"] == "robot":
            continue
        obj = obd_rides.get(row["seq"])
        if not obj:
            continue
        path = find_spr(obj["folder"], obj["wait"])
        if path is None:
            continue
        key = f"ride-{row['seq']}"
        before = key in pd["sprites"]
        if not ensure_sprite(path, key, dests, cache, pd, "ride", reference, tolerance):
            continue
        if not before:
            new_sprites += 1
        names, ids = [], []
        for it in group:
            if it["name"] not in names:
                names.append(it["name"])
            ids.append(it["id"])
        ids = sorted(set(ids))
        comps = {s: {"standing": {}, "mounted": {"ride": key}} for s in ("male", "female")}
        added.append({
            "visualId": f"local-ride-{look}-{ids[0]}",
            "kind": "ride",
            "item_id": ids[0],
            "itemIds": ids,
            "appearanceIds": [look],
            "name": names[0],
            "aliases": names[:8],
            "sexes": ["male", "female"],
            "placements": [{"id": "ride", "occupies": ["ride"], "layers": ["ride"]}],
            "flags": {
                "headCover": "none",
                "robe": False,
                "capeLayer": False,
                "twoHanded": False,
                "flexibleHands": False,
            },
            "componentIds": {"ride": row["seq"]},
            "components": comps,
            "ride": {
                "appearanceId": look,
                "sequence": row["seq"],
                "sprite": key,
                "riderOffsetY": row["y"],
                "layerMode": "ride",
            },
            "local": True,
        })

    print(f"  extracted {len(added)} mounts, {new_sprites} new atlases")

    wear_added = 0
    mixed_flexible: list[int] = []
    for look, group in wears.items():
        doll = dolls[look]
        flexible = group_flexible(group, mixed_flexible)
        flags = {
            "headCover": doll["headCover"],
            "robe": bool(doll["robe"]),
            "capeLayer": bool(doll["capeLayer"]),
            "twoHanded": False,
            "flexibleHands": flexible,
        }
        sexes: list[str] = []
        comps = {"male": {"standing": {}, "mounted": {}}, "female": {"standing": {}, "mounted": {}}}
        component_ids = {}
        ok = False
        for slot, comp in doll["parts"].items():
            layer = layer_for(slot, flags)
            component_ids[slot] = comp
            role = "weapon" if slot in ("main", "off") else "wear"
            for sex in ("male", "female"):
                resolved = resolve_item(comp, sex, obd_items, "main")
                if not resolved:
                    continue
                key, wait, sit = resolved
                before = key in pd["sprites"]
                if not ensure_sprite(wait, key, dests, cache, pd, role, reference, tolerance):
                    continue
                if not before:
                    new_sprites += 1
                comps[sex]["standing"][layer] = key
                comps[sex]["mounted"][layer] = mounted_key(
                    sit, key, dests, cache, pd, role, reference, tolerance
                )
                if flexible and slot == "main":
                    component_ids["off"] = comp
                    left = resolve_item(comp, sex, obd_items, "off")
                    off_key = key
                    if left:
                        lkey, lwait, lsit = left
                        before_l = lkey in pd["sprites"]
                        if ensure_sprite(lwait, lkey, dests, cache, pd, "weapon", reference, tolerance):
                            if not before_l and lkey != key:
                                new_sprites += 1
                            off_key = lkey
                            comps[sex]["mounted"]["off"] = mounted_key(
                                lsit, lkey, dests, cache, pd, "weapon", reference, tolerance
                            )
                        else:
                            comps[sex]["mounted"]["off"] = comps[sex]["mounted"][layer]
                    else:
                        comps[sex]["mounted"]["off"] = comps[sex]["mounted"][layer]
                    comps[sex]["standing"]["off"] = off_key
                if sex not in sexes:
                    sexes.append(sex)
                ok = True
        if not ok:
            continue
        place = placements_for(component_ids, flags)
        if not place or not place[0].get("occupies"):
            continue
        names, ids = [], []
        for it in group:
            if it["name"] not in names:
                names.append(it["name"])
            ids.append(it["id"])
        ids = sorted(set(ids))
        added.append({
            "visualId": f"local-{look}-{ids[0]}",
            "kind": "wearable",
            "item_id": ids[0],
            "itemIds": ids,
            "appearanceIds": [look],
            "name": names[0],
            "aliases": names[:8],
            "collection": doll["collection"],
            "collectionRaw": doll["collectionRaw"],
            "sexes": sexes or ["female"],
            "placements": place,
            "flags": flags,
            "componentIds": component_ids,
            "components": comps,
            "local": True,
        })
        wear_added += 1
        if wear_added % 200 == 0:
            print(f"  wear {wear_added}...")

    if mixed_flexible:
        print(
            f"warning: flexibleHands disagreed inside {len(mixed_flexible)} look-groups; "
            f"left False for those groups"
        )
    print("warning: twoHanded left False on every local record; no source column")

    pd["items"].extend(added)
    prune_unreferenced(pd)
    retint_null_sprites(pd)
    write_tint_masks(pd)
    write_catalog(pd)
    print(f"added {len(added)} groups ({sum(1 for i in added if i['kind']=='ride')} rides), {new_sprites} new atlases")
    print(f"catalog {len(pd['items'])} records, {len(pd['sprites'])} sprites")
    print(f"wrote {CATALOG} ({CATALOG.stat().st_size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retint",
        action="store_true",
        help="Fill null tints from existing PNGs and prune unreferenced sprites. Does not read the client extract.",
    )
    args = parser.parse_args()
    if args.retint:
        retint_and_prune()
    else:
        main()
