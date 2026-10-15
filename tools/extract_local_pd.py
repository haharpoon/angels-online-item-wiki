"""Extract local Wait.spr atlases using CHARDEF.XML + char*.obd."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from client_paths import configured_extract
from client_pd_map import EXTRACT, find_spr, load_ride_rows, parse_obd, ride_by_appearance
from ewsp import decode_wait, is_placeholder_size, pack_atlas
from translate_text import translate_catalog_display_text

# The wiki dummy is the classic ~82px body. Later packs drop a second sheet in
# the same folder: either a 12xxxx Wait.spr, or the same id plus 5000
# (75038 next to 70038, 26212 next to 21212). Those are anchored for a taller
# body and float above this dummy. 800x600 sheets are empty placeholders.
CLASSIC_BODY = 82
EXPECTED_FRAMES = 15
# Pixels within this distance of skin reference (255, 202, 156) are skin.
# 130 recolours grey, gold, brown and leather; 36 stays on the skin swatch.
SKIN_TOLERANCE = 36
DOLL_TYPE = "紙娃娃"
MOUNT_TYPE = "座騎"
MECHA_TYPE = "機甲"
# Normal gear is not a doll row. The slot comes from the item type and the
# component id is 原型外觀 itself (the chr/i#### object), not doll[look].
TYPE_SLOT = {
    "劍": "main", "刀": "main", "斧": "main", "錘": "main", "槍": "main",
    "杖": "main", "弓箭": "main", "彈弓": "main", "影刃": "main",
    "盾": "off",
    "衣服": "body", "頭飾": "head", "手套": "hands", "鞋子": "feet",
    "披風": "back", "背包": "back",
}
# Two-handed when the type says so and the left hand is empty or has no L sheet.
TWO_HAND_TYPES = {"弓箭", "槍", "杖", "斧", "錘"}
ASIAN_TEXT = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
LATIN_TEXT = re.compile(r"[A-Za-z]")
SHEET_ID = re.compile(r"(\d+)")

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
    DOLL_TYPE, MOUNT_TYPE, MECHA_TYPE,
    *TYPE_SLOT.keys(),
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
    extra_names = [c for c in (
        "頭部全罩", "頭部半罩", "身體袍", "背部另一層", "收藏類別", "主手裝備", "副手裝備",
        "變身換圖",
    ) if c in cols]
    for col, flag in (
        ("身體袍", "robe"),
        ("背部另一層", "capeLayer"),
        ("收藏類別", "collection"),
        ("變身換圖", "shapeshift"),
    ):
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
            "mainHand": _yes(extra_vals.get("主手裝備")) if "主手裝備" in cols else False,
            "offHand": _yes(extra_vals.get("副手裝備")) if "副手裝備" in cols else False,
            "shapeshift": _yes(extra_vals.get("變身換圖")) if "變身換圖" in cols else False,
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
        extra_cols = [c for c in (
            "右手裝備", "左手裝備", "身體袍", "背部另一層", "頭部全罩", "頭部半罩", "男女裝備",
        ) if c in cols]
        if "右手裝備" not in extra_cols or "左手裝備" not in extra_cols:
            print(f"warning: {table} missing 右手裝備/左手裝備; flexibleHands left False for its rows")
        sel_extra = "".join(f', "{c}"' for c in extra_cols)
        sel = f'select "id", "原型外觀", "物品類別", {name_sql}{sel_extra} from {table}'
        try:
            rows = list(con.execute(sel))
        except sqlite3.OperationalError:
            continue
        for row in rows:
            iid, look, typ, name, *extra = row
            if typ not in WEAR_TYPES:
                continue
            item_id, appearance = _int(iid), _int(look)
            if item_id is None or appearance is None:
                continue
            fields = dict(zip(extra_cols, extra))
            rec = {
                "id": item_id,
                "look": appearance,
                "type": typ,
                "name": str(name or item_id),
                "robe": _yes(fields.get("身體袍")),
                "cape": _yes(fields.get("背部另一層")),
                "fullHead": _yes(fields.get("頭部全罩")),
                "halfHead": _yes(fields.get("頭部半罩")),
                "sex": str(fields.get("男女裝備") or "").strip(),
            }
            if "右手裝備" in fields and "左手裝備" in fields:
                rec["right"] = _yes(fields.get("右手裝備"))
                rec["left"] = _yes(fields.get("左手裝備"))
                rec["flexible"] = rec["right"] and rec["left"]
            out.append(rec)
    return out


def skin_reference(pd: dict) -> tuple[int, int, int]:
    """Identity swatch. Tone 0 is that colour with a zero offset."""
    tones = ((pd.get("customization") or {}).get("skinTones") or [{}])
    tone = tones[0] if tones else {}
    ref = tone.get("reference") or [255, 202, 156]
    return (int(ref[0]), int(ref[1]), int(ref[2]))


def apply_skin_tolerance(pd: dict) -> None:
    """Publish the same tolerance the mask is built with."""
    for tone in ((pd.get("customization") or {}).get("skinTones") or []):
        tone["tolerance"] = 0 if int(tone.get("id") or 0) == 0 else SKIN_TOLERANCE


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
    """Tint only atlases that actually contain skin. Weapons and mounts stay plain.

    Clothing with zero pixels near the skin swatch used to be marked skin anyway,
    and tolerance 130 then recoloured gold, grey and leather.
    """
    if role == "hair":
        return "hair"
    if role == "base":
        return "skin"
    if role in ("ride", "weapon"):
        return "none"
    return "skin" if hits else "none"


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
    packed = pack_atlas(frames)
    if not packed:
        return None
    atlas, meta, cell_w, cell_h = packed
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


_sheet_choice: dict[tuple[str, str, str], Path | None] = {}


def sheet_number(path: Path) -> int | None:
    match = SHEET_ID.search(path.stem)
    if not match:
        return None
    return int(match.group(1))


def shadow_sheet_ids(numbers: set[int]) -> set[int]:
    """Ids of the tall sheets that float on the classic ~82px dummy.

    A 12xxxx file is one of those sheets. So is a file whose id is exactly
    5000 above another sheet in the same folder (75038 beside 70038).
    """
    bad: set[int] = set()
    for number in numbers:
        if 120000 <= number < 130000:
            bad.add(number)
        if (number - 5000) in numbers:
            bad.add(number)
    return bad


def prefer_classic_sheet(path: Path | None, kind: str) -> Path | None:
    """Use the declared sheet unless it is a placeholder or a tall shadow.

    `kind` is ``wait`` or ``sit``. Closeness to the classic body height is not
    a vote: a hat is ~20px, and the shadow sheet often wins that contest.
    """
    if path is None:
        return None
    folder = path.parent
    key = (str(folder), kind, path.name.lower())
    if key in _sheet_choice:
        return _sheet_choice[key]
    if not folder.is_dir():
        _sheet_choice[key] = path if path.is_file() else None
        return _sheet_choice[key]
    candidates = [
        cand for cand in folder.iterdir()
        if cand.suffix.lower() == ".spr" and kind in cand.name.lower()
    ]
    if path not in candidates and path.is_file():
        candidates.append(path)
    numbers = {n for cand in candidates if (n := sheet_number(cand)) is not None}
    shadows = shadow_sheet_ids(numbers)

    def usable(cand: Path) -> bool:
        number = sheet_number(cand)
        if number is not None and number in shadows:
            return False
        return decode_wait(cand) is not None

    chosen: Path | None = None
    if path.is_file() and usable(path):
        chosen = path
    else:
        for cand in sorted(candidates, key=lambda cand: (sheet_number(cand) or 0, cand.name.lower())):
            if cand == path or not usable(cand):
                continue
            why = "tall shadow" if sheet_number(path) in shadows else "unusable"
            print(f"  {path.name} is {why}; using {cand.name}")
            chosen = cand
            break
    if chosen is None and path.is_file() and decode_wait(path):
        print(f"  warning: only sheet for {path.name} is a tall or placeholder-adjacent file; keeping it")
        chosen = path
    elif chosen is None and sheet_number(path) in shadows:
        print(f"  skip {path.name}: tall sheet and no classic alternative")
    _sheet_choice[key] = chosen
    return chosen


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
    wait = prefer_classic_sheet(find_spr(rec["folder"], rec["wait"]), "wait")
    if wait is None:
        return None
    sit = prefer_classic_sheet(find_spr(rec["folder"], rec["sit"]), "sit") if rec.get("sit") else None
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
        extra = [s for s in slots if s not in ("main", "off")]
        return [{
            "id": "both",
            "occupies": ["main", "off", *extra],
            "layers": ["main", *[layer_for(s, flags) for s in extra]],
        }]
    if flags.get("flexibleHands") and hand_only:
        return [
            {"id": "main", "occupies": ["main"], "layers": ["main"]},
            {"id": "off", "occupies": ["off"], "layers": ["off"]},
        ]
    layers = [layer_for(s, flags) for s in slots]
    return [{"id": "default", "occupies": slots, "layers": layers}]


def has_cjk(text: str) -> bool:
    return bool(ASIAN_TEXT.search(text or ""))


def choose_display_name(names: list[str]) -> tuple[str, list[str]]:
    """Prefer an English item-table name over a Chinese or Japanese one."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for name in names:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    if not cleaned:
        return "", []
    english = [name for name in cleaned if LATIN_TEXT.search(name) and not has_cjk(name)]
    primary = english[0] if english else cleaned[0]
    aliases = [primary] + [name for name in cleaned if name != primary]
    return primary, aliases[:8]


def derive_two_handed(
    *,
    slot: str,
    types: set[str],
    right_flags: list[bool],
    left_flags: list[bool],
    has_l_sprite: bool,
    doll: dict | None,
) -> bool:
    """Bow, spear, staff, axe and hammer are two-handed when the off hand is empty.

    A paper-doll weapon whose doll row sets 副手裝備 without its own 副手 part is
    the same idea, and so is a weapon with both hand flags but no L sheet
    (the cool chainsaw). An L sheet means the piece can actually sit in the off hand.
    """
    if slot != "main":
        return False
    both = bool(left_flags) and bool(right_flags) and all(
        right and left for right, left in zip(right_flags, left_flags)
    )
    left_empty = not left_flags or all(not left for left in left_flags)
    parts = (doll or {}).get("parts") or {}
    doll_two = bool(parts.get("main")) and not parts.get("off") and bool((doll or {}).get("offHand"))
    if doll_two and not has_l_sprite:
        return True
    if both and not has_l_sprite:
        return True
    if types & TWO_HAND_TYPES and (left_empty or not has_l_sprite):
        return True
    return False


def derive_flexible(
    *,
    slot: str,
    two_handed: bool,
    right_flags: list[bool],
    left_flags: list[bool],
    has_l_sprite: bool,
) -> bool:
    """Either hand, only when every row agrees and a distinct L sheet exists."""
    if two_handed or slot != "main" or not has_l_sprite:
        return False
    if not right_flags or len(right_flags) != len(left_flags):
        return False
    return all(right and left for right, left in zip(right_flags, left_flags))


def hands_disagree(group: list[dict]) -> bool:
    if any("flexible" not in it for it in group):
        return any(it.get("flexible") for it in group)
    flags = [bool(it.get("flexible")) for it in group]
    return any(flags) and not all(flags)


def classify_local_item(it: dict, doll_ids: set[int]) -> str | None:
    """Where a not-yet-catalogued wearable goes.

    Paper dolls are the only rows whose look id is a doll-table id. Mounts and
    mecha use the ride path. Clothes and weapons use their own type slot, even
    when that look number also exists in the doll table.
    """
    if it["type"] == MOUNT_TYPE:
        return "mount"
    if it["type"] == MECHA_TYPE:
        return "mecha"
    if it["type"] == DOLL_TYPE:
        return "doll" if it["look"] in doll_ids else None
    if TYPE_SLOT.get(it["type"]):
        return "gear"
    return None


def sexes_for(group: list[dict]) -> list[str]:
    marks = {it.get("sex") or "" for it in group}
    if marks == {"限女性"}:
        return ["female"]
    if marks == {"限男性"}:
        return ["male"]
    return ["male", "female"]


def gear_flags(group: list[dict], slot: str) -> dict:
    full = any(it.get("fullHead") for it in group)
    half = any(it.get("halfHead") for it in group)
    return {
        "headCover": "full" if full else ("half" if half else "none"),
        "robe": slot == "body" and any(it.get("robe") for it in group),
        "capeLayer": slot == "back" and any(it.get("cape") for it in group),
    }


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


def sprite_png(key: str, rec: dict | None = None) -> Path | None:
    """Find the atlas the preview will draw.

    New extracts are saved as ``{key}.png``. Older wiki records often point
    ``url`` at a shared sheet with a different filename, and that is the file
    ``preview.js`` loads.
    """
    names = [f"{key}.png"]
    if rec:
        base = str(rec.get("url") or "").replace("\\", "/").rsplit("/", 1)[-1]
        if base and base not in names:
            names.append(base)
    for name in names:
        for folder in SPRITE_DIRS:
            path = folder / name
            if path.is_file() and path.stat().st_size >= 32:
                return path
    return None


def retint_sprites(pd: dict) -> Counter:
    """Set tint from real skin pixels. Weapons and mounts stay none."""
    apply_skin_tolerance(pd)
    reference = skin_reference(pd)
    print(f"skin match reference {list(reference)} tolerance {SKIN_TOLERANCE}")
    layers = layers_by_sprite(pd)
    counts: Counter = Counter()
    changed = 0
    for key, rec in pd["sprites"].items():
        role = sprite_role(key, layers.get(key))
        placeholder = is_placeholder_size(int(rec.get("cellWidth") or 0), int(rec.get("cellHeight") or 0))
        hits = 0
        if role == "wear" and not placeholder:
            png = sprite_png(key, rec)
            if png is not None:
                with Image.open(png) as image:
                    hits = count_skin_pixels(image, reference, SKIN_TOLERANCE)
        tint = "none" if placeholder else choose_tint(role, hits)
        if rec.get("tint") != tint:
            changed += 1
        rec["tint"] = tint
        counts[tint] += 1
    print(f"retinted {changed} sprites; breakdown {dict(counts)}")
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
    skin_tones = custom.get("skinTones") or []
    if skin_tones:
        ref = tuple(int(v) for v in (skin_tones[0].get("reference") or [255, 202, 156]))
        specs["skin"] = (ref, SKIN_TOLERANCE * SKIN_TOLERANCE)
    hair_tones = custom.get("hairColors") or []
    if hair_tones:
        ref = tuple(int(v) for v in (hair_tones[0].get("reference") or [0, 0, 0]))
        tol = max(int(tone.get("tolerance") or 0) for tone in hair_tones)
        specs["hair"] = (ref, tol * tol)
    masks = {}
    for key, rec in pd.get("sprites", {}).items():
        tint = rec.get("tint")
        if tint not in specs:
            continue
        png = sprite_png(key, rec)
        if png is None:
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
    try:
        translate_catalog_display_text(pd)
    except Exception as exc:
        print(f"warning: translation skipped ({exc}); kept item-table names")
    dump_catalog(pd)


def verify_sprite_files(pd: dict) -> None:
    """Fail the build when a referenced atlas has no PNG or is an 800×600 stand-in."""
    missing = []
    placeholders = []
    for key in sorted(referenced_sprite_keys(pd)):
        rec = pd.get("sprites", {}).get(key) or {}
        if is_placeholder_size(int(rec.get("cellWidth") or 0), int(rec.get("cellHeight") or 0)):
            placeholders.append(key)
        if sprite_png(key, rec) is None:
            missing.append(key)
    if placeholders:
        print(f"error: {len(placeholders)} referenced atlases are 800x600 placeholders")
        print("  " + ", ".join(placeholders[:12]))
    if missing:
        print(f"error: {len(missing)} referenced sprites have no PNG in {SPRITE_DIR}")
        print("  " + ", ".join(missing[:12]))
        print("Re-run with AO_EXTRACT pointed at the extracted client:")
        print("  py -3 tools/extract_local_pd.py")
    if missing or placeholders:
        raise SystemExit(1)


def retint_and_prune() -> None:
    print("loading catalog...")
    pd = json.loads(CATALOG.read_text(encoding="utf-8"))
    print(f"  {len(pd['items'])} items, {len(pd['sprites'])} sprites, local {sum(1 for i in pd['items'] if i.get('local'))}")
    audit_source_flags()
    prune_unreferenced(pd)
    retint_sprites(pd)
    write_tint_masks(pd)
    dump_catalog(pd)
    print(f"catalog {len(pd['items'])} records, {len(pd['sprites'])} sprites")
    print(f"wrote {CATALOG} ({CATALOG.stat().st_size} bytes)")
    verify_sprite_files(pd)


def appearance_index(items: list[dict]) -> dict[tuple[str, int], dict]:
    found: dict[tuple[str, int], dict] = {}
    for rec in items:
        for app in rec.get("appearanceIds") or []:
            found.setdefault((rec["kind"], int(app)), rec)
    return found


def hand_lists(group: list[dict]) -> tuple[list[bool], list[bool]]:
    rights, lefts = [], []
    for it in group:
        if "right" in it and "left" in it:
            rights.append(bool(it["right"]))
            lefts.append(bool(it["left"]))
    return rights, lefts


def prefer_english_name(rec: dict, extra_names: list[str]) -> bool:
    """Replace a CJK catalog name when the item table has an English one."""
    current = str(rec.get("name") or "")
    primary, _aliases = choose_display_name([current, *(rec.get("aliases") or []), *extra_names])
    changed = False
    if primary and has_cjk(current) and not has_cjk(primary) and primary != current:
        aliases = list(rec.get("aliases") or [])
        if current and current not in aliases:
            aliases.append(current)
        if primary not in aliases:
            aliases.insert(0, primary)
        rec["name"] = primary
        rec["aliases"] = aliases[:8]
        changed = True
    aliases = list(rec.get("aliases") or [])
    for name in extra_names:
        text = str(name or "").strip()
        if text and text != rec.get("name") and text not in aliases and len(aliases) < 8:
            aliases.append(text)
            changed = True
    if aliases != list(rec.get("aliases") or []):
        rec["aliases"] = aliases
    return changed


def merge_into(rec: dict, group: list[dict]) -> int:
    """Add item ids to an existing look. Does not create a second record."""
    ids = {int(x) for x in (rec.get("itemIds") or [])}
    if rec.get("item_id") is not None:
        ids.add(int(rec["item_id"]))
    before = len(ids)
    names = []
    for it in group:
        names.append(it["name"])
        ids.add(int(it["id"]))
    rec["itemIds"] = sorted(ids)
    prefer_english_name(rec, names)
    return len(ids) - before


def attach_known_ids(pd: dict, db: Path = DB) -> None:
    """Link extra 紙娃娃 and 座騎 ids onto looks the catalog already has."""
    items = load_items(db)
    indexed = appearance_index(pd["items"])
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    by_id: dict[int, str] = {}
    for it in items:
        by_id.setdefault(it["id"], it["name"])
        if it["type"] == DOLL_TYPE:
            groups[("wearable", it["look"])].append(it)
        elif it["type"] in (MOUNT_TYPE, MECHA_TYPE):
            groups[("ride", it["look"])].append(it)
    attached = 0
    for key, group in groups.items():
        rec = indexed.get(key)
        if rec:
            attached += merge_into(rec, group)
    renamed = 0
    for rec in pd["items"]:
        before = rec.get("name")
        extra = [by_id[iid] for iid in (rec.get("itemIds") or []) if iid in by_id]
        prefer_english_name(rec, extra)
        if rec.get("name") != before and not has_cjk(str(rec.get("name") or "")):
            renamed += 1
    print(f"attached {attached} item ids to existing looks; English names applied on {renamed} records")


def scrub_sprite_keys(pd: dict, keys: set[str]) -> int:
    """Drop component links to sheets we refused to ship."""
    removed = 0
    for item in pd.get("items") or []:
        ride = item.get("ride")
        if isinstance(ride, dict) and ride.get("sprite") in keys:
            ride.pop("sprite", None)
            removed += 1
        for sex in (item.get("components") or {}).values():
            if not isinstance(sex, dict):
                continue
            for pose in sex.values():
                if not isinstance(pose, dict):
                    continue
                for layer, key in list(pose.items()):
                    if key in keys:
                        del pose[layer]
                        removed += 1
    return removed


def drop_placeholders(pd: dict) -> int:
    drop = [
        key for key, rec in pd["sprites"].items()
        if is_placeholder_size(int(rec.get("cellWidth") or 0), int(rec.get("cellHeight") or 0))
    ]
    # Also forget links whose record was already removed on a previous run.
    linked = referenced_sprite_keys(pd)
    for key in list(linked):
        rec = pd["sprites"].get(key) or {}
        if is_placeholder_size(int(rec.get("cellWidth") or 0), int(rec.get("cellHeight") or 0)):
            if key not in drop:
                drop.append(key)
    scrub_sprite_keys(pd, set(drop))
    for key in drop:
        pd["sprites"].pop(key, None)
        for folder in SPRITE_DIRS:
            path = folder / f"{key}.png"
            if path.is_file():
                path.unlink()
    if drop:
        print(f"removed {len(drop)} placeholder atlases (800x600) and unlinked them")
        print("  " + ", ".join(drop[:12]))
    return len(drop)


def client_sprite_path(source: str) -> Path | None:
    """Map a catalog sourceAsset onto AO_EXTRACT, including the owner's old absolute paths."""
    if not source:
        return None
    text = source.replace("\\", "/")
    root = configured_extract() or EXTRACT
    lower = text.lower()
    candidates = []
    marker = "/extracted/"
    if marker in lower:
        candidates.append(root / text[lower.index(marker) + len(marker):])
    if lower.startswith("data/"):
        candidates.append(root / text.split("/", 1)[1])
    candidates.append(Path(text))
    candidates.append(root / text)
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def dedicated_sprite_png(key: str) -> Path | None:
    """A PNG named for the sprite key, not a shared sheet another record points at."""
    for folder in SPRITE_DIRS:
        path = folder / f"{key}.png"
        if path.is_file() and path.stat().st_size >= 32:
            return path
    return None


def backfill_missing(pd: dict, reference: tuple[int, int, int]) -> int:
    """Decode a `{key}.png` for every referenced sprite that does not have one.

    A wiki record whose `url` names a different file still draws, but that shared
    sheet is often a different component. When the client extract is present,
    replace it with the sheet from `sourceAsset`.
    """
    layers = layers_by_sprite(pd)
    dests = [SPRITE_DIR, SHARE_SPRITE]
    cache: dict[str, dict] = {}
    filled = 0
    for key in sorted(referenced_sprite_keys(pd)):
        rec = pd["sprites"].get(key)
        if not rec:
            continue
        if dedicated_sprite_png(key):
            continue
        found = client_sprite_path(str(rec.get("sourceAsset") or ""))
        if found is None:
            continue
        kind = "sit" if "sit" in found.name.lower() else "wait"
        chosen = prefer_classic_sheet(found, kind)
        if chosen is None:
            continue
        saved = pd["sprites"].pop(key)
        role = sprite_role(key, layers.get(key))
        if ensure_sprite(chosen, key, dests, cache, pd, role, reference, SKIN_TOLERANCE):
            filled += 1
        else:
            pd["sprites"][key] = saved
    print(f"backfilled {filled} missing atlases from the client extract")
    return filled


def has_distinct_off(comp: int, sexes: list[str], obd_items: dict) -> bool:
    for sex in sexes:
        main = resolve_item(comp, sex, obd_items, "main")
        off = resolve_item(comp, sex, obd_items, "off")
        if main and off and off[1] != main[1]:
            return True
    return False


def names_and_ids(group: list[dict]) -> tuple[str, list[str], list[int]]:
    primary, aliases = choose_display_name([it["name"] for it in group])
    ids = sorted({it["id"] for it in group})
    return primary or str(ids[0]), aliases or [primary or str(ids[0])], ids


def empty_flags() -> dict:
    return {
        "headCover": "none",
        "robe": False,
        "capeLayer": False,
        "twoHanded": False,
        "flexibleHands": False,
        "shapeshift": False,
    }


def extract_ride_group(
    pd: dict,
    look: int,
    group: list[dict],
    ride_rows: list[dict],
    obd_rides: dict,
    dests: list[Path],
    cache: dict,
    reference: tuple[int, int, int],
    *,
    allow_robot: bool,
) -> tuple[dict | None, int]:
    row = ride_by_appearance(ride_rows, look)
    if not row:
        return None, 0
    if row["layer"] == "robot" and not allow_robot:
        return None, 0
    obj = obd_rides.get(row["seq"])
    if not obj:
        return None, 0
    path = prefer_classic_sheet(find_spr(obj["folder"], obj["wait"]), "wait")
    if path is None:
        return None, 0
    key = f"ride-{row['seq']}"
    before = key in pd["sprites"]
    if not ensure_sprite(path, key, dests, cache, pd, "ride", reference, SKIN_TOLERANCE):
        return None, 0
    name, aliases, ids = names_and_ids(group)
    comps = {sex: {"standing": {}, "mounted": {"ride": key}} for sex in ("male", "female")}
    rec = {
        "visualId": f"local-ride-{look}-{ids[0]}",
        "kind": "ride",
        "item_id": ids[0],
        "itemIds": ids,
        "appearanceIds": [look],
        "name": name,
        "aliases": aliases,
        "sexes": ["male", "female"],
        "placements": [{"id": "ride", "occupies": ["ride"], "layers": ["ride"]}],
        "flags": empty_flags(),
        "componentIds": {"ride": row["seq"]},
        "components": comps,
        "ride": {
            "appearanceId": look,
            "sequence": row["seq"],
            "sprite": key,
            "riderOffsetY": row["y"],
            "layerMode": row["layer"],
        },
        "local": True,
    }
    return rec, 0 if before else 1


def paint_part(
    pd: dict,
    comp: int,
    sex: str,
    hand: str,
    role: str,
    dests: list[Path],
    cache: dict,
    obd_items: dict,
    reference: tuple[int, int, int],
) -> tuple[str, str] | None:
    """Return (standing key, mounted key) after the sheet is on disk."""
    resolved = resolve_item(comp, sex, obd_items, hand)
    if not resolved:
        return None
    key, wait, sit = resolved
    if not ensure_sprite(wait, key, dests, cache, pd, role, reference, SKIN_TOLERANCE):
        return None
    mounted = mounted_key(sit, key, dests, cache, pd, role, reference, SKIN_TOLERANCE)
    return key, mounted


def extract_wear_group(
    pd: dict,
    look: int,
    group: list[dict],
    *,
    doll: dict | None,
    slot: str | None,
    component: int | None,
    obd_items: dict,
    dests: list[Path],
    cache: dict,
    reference: tuple[int, int, int],
    mixed: list[int],
) -> tuple[dict | None, int]:
    """One local wearable. Doll rows supply every part; normal gear supplies one slot."""
    if doll is not None:
        part_slots = list(doll["parts"].items())
        base_flags = {
            "headCover": doll["headCover"],
            "robe": bool(doll["robe"]),
            "capeLayer": bool(doll["capeLayer"]),
        }
        collection = doll.get("collection")
        collection_raw = doll.get("collectionRaw")
        visual = f"local-{look}"
    else:
        if slot is None or component is None:
            return None, 0
        part_slots = [(slot, component)]
        base_flags = gear_flags(group, slot)
        collection = None
        collection_raw = None
        visual = f"local-{slot}-{component}"
    sexes = sexes_for(group)
    # Shields and any off-hand part use the L sheet. Main-hand weapons use it
    # only when the group can actually sit in the off hand.
    rights, lefts = hand_lists(group)
    weapon_slot = "main" if any(part == "main" for part, _comp in part_slots) else (slot or "")
    probe_comp = component if component is not None else next(
        (comp for part, comp in part_slots if part == "main"), None
    )
    has_l = bool(probe_comp) and has_distinct_off(int(probe_comp), sexes, obd_items)
    if hands_disagree(group):
        mixed.append(look)
    two = derive_two_handed(
        slot=weapon_slot if weapon_slot == "main" else "",
        types={it["type"] for it in group},
        right_flags=rights,
        left_flags=lefts,
        has_l_sprite=has_l,
        doll=doll,
    )
    flexible = derive_flexible(
        slot=weapon_slot if weapon_slot == "main" else "",
        two_handed=two,
        right_flags=rights,
        left_flags=lefts,
        has_l_sprite=has_l,
    )
    flags = {
        **base_flags,
        "twoHanded": two,
        "flexibleHands": flexible,
        # 變身換圖 dolls are a whole character sprite, not a clothing layer.
        "shapeshift": bool(doll and doll.get("shapeshift")),
    }
    comps = {sex: {"standing": {}, "mounted": {}} for sex in ("male", "female")}
    component_ids: dict[str, int] = {}
    used: list[str] = []
    new_sprites = 0
    for part, comp in part_slots:
        layer = layer_for(part, flags)
        hand = "off" if part == "off" else "main"
        role = "weapon" if part in ("main", "off") else "wear"
        part_ok = False
        for sex in sexes:
            before_keys = set(pd["sprites"])
            painted = paint_part(
                pd, comp, sex, hand, role, dests, cache, obd_items, reference,
            )
            if not painted:
                continue
            key, mounted = painted
            comps[sex]["standing"][layer] = key
            comps[sex]["mounted"][layer] = mounted
            new_sprites += len(set(pd["sprites"]) - before_keys)
            if flexible and part == "main":
                left = paint_part(
                    pd, comp, sex, "off", "weapon", dests, cache, obd_items, reference,
                )
                off_key, off_mounted = left if left else (key, mounted)
                comps[sex]["standing"]["off"] = off_key
                comps[sex]["mounted"]["off"] = off_mounted
            if sex not in used:
                used.append(sex)
            part_ok = True
        if part_ok:
            component_ids[part] = comp
            if flexible and part == "main":
                component_ids["off"] = comp
    if not component_ids:
        return None, new_sprites
    place = placements_for(component_ids, flags)
    if not place or not place[0].get("occupies"):
        return None, new_sprites
    name, aliases, ids = names_and_ids(group)
    rec = {
        "visualId": f"{visual}-{ids[0]}",
        "kind": "wearable",
        "item_id": ids[0],
        "itemIds": ids,
        "appearanceIds": [look],
        "name": name,
        "aliases": aliases,
        "sexes": used or sexes,
        "placements": place,
        "flags": flags,
        "componentIds": component_ids,
        "components": comps,
        "local": True,
    }
    if collection:
        rec["collection"] = collection
        rec["collectionRaw"] = collection_raw
    return rec, new_sprites


def finish_catalog(pd: dict, reference: tuple[int, int, int]) -> None:
    backfill_missing(pd, reference)
    drop_placeholders(pd)
    prune_unreferenced(pd)
    retint_sprites(pd)
    write_tint_masks(pd)
    write_catalog(pd)
    print(f"catalog {len(pd['items'])} records, {len(pd['sprites'])} sprites")
    print(f"wrote {CATALOG} ({CATALOG.stat().st_size} bytes)")
    verify_sprite_files(pd)


def repair_catalog() -> None:
    """Fix committed catalog data that does not need the game client."""
    print("loading catalog...")
    pd = json.loads(CATALOG.read_text(encoding="utf-8"))
    attach_known_ids(pd)
    reference = skin_reference(pd)
    finish_catalog(pd, reference)


def main() -> None:
    print("loading catalog...")
    pd = json.loads(CATALOG.read_text(encoding="utf-8"))
    kept = [it for it in pd["items"] if not it.get("local")]
    pd["items"] = kept
    attach_known_ids(pd)
    wiki_ids = set()
    indexed = appearance_index(pd["items"])
    for it in pd["items"]:
        wiki_ids.add(it["item_id"])
        wiki_ids.update(it.get("itemIds") or [])
    print(f"  kept {len(pd['items'])} wiki records")
    audit_source_flags()

    print("loading CHARDEF + OBD...")
    ride_rows = load_ride_rows()
    obd_items, obd_rides = parse_obd()
    print(f"  {len(ride_rows)} CHARDEF rides, {len(obd_rides)} H objects, {len(obd_items)} I objects")

    dolls = load_dolls(DB)
    items = load_items(DB)
    dests = [SPRITE_DIR, SHARE_SPRITE]
    cache: dict[str, dict] = {}
    added: list[dict] = []
    new_sprites = 0
    reference = skin_reference(pd)
    apply_skin_tolerance(pd)
    print(f"skin match reference {list(reference)} tolerance {SKIN_TOLERANCE}")

    mounts: dict[int, list[dict]] = defaultdict(list)
    mechas: dict[int, list[dict]] = defaultdict(list)
    dolls_groups: dict[int, list[dict]] = defaultdict(list)
    gear: dict[tuple[str, int], list[dict]] = defaultdict(list)
    doll_ids = set(dolls)
    for it in items:
        if it["id"] in wiki_ids:
            continue
        bucket = classify_local_item(it, doll_ids)
        if bucket == "mount":
            mounts[it["look"]].append(it)
        elif bucket == "mecha":
            mechas[it["look"]].append(it)
        elif bucket == "doll":
            dolls_groups[it["look"]].append(it)
        elif bucket == "gear":
            gear[(it["type"], it["look"])].append(it)

    print(
        f"  local mount groups {len(mounts)}, mecha {len(mechas)}, "
        f"doll groups {len(dolls_groups)}, gear groups {len(gear)}"
    )

    def take_existing(kind: str, look: int, group: list[dict]) -> bool:
        rec = indexed.get((kind, look))
        if not rec:
            return False
        merge_into(rec, group)
        return True

    for look, group in mounts.items():
        if take_existing("ride", look, group):
            continue
        rec, spawned = extract_ride_group(
            pd, look, group, ride_rows, obd_rides, dests, cache, reference, allow_robot=False,
        )
        new_sprites += spawned
        if rec:
            added.append(rec)
            indexed[("ride", look)] = rec

    for look, group in mechas.items():
        if take_existing("ride", look, group):
            continue
        rec, spawned = extract_ride_group(
            pd, look, group, ride_rows, obd_rides, dests, cache, reference, allow_robot=True,
        )
        new_sprites += spawned
        if rec:
            added.append(rec)
            indexed[("ride", look)] = rec

    print(f"  extracted {sum(1 for i in added if i['kind']=='ride')} mounts/mecha, {new_sprites} new atlases")

    mixed_flexible: list[int] = []
    wear_added = 0
    for look, group in dolls_groups.items():
        if take_existing("wearable", look, group):
            continue
        rec, spawned = extract_wear_group(
            pd, look, group, doll=dolls[look], slot=None, component=None,
            obd_items=obd_items, dests=dests, cache=cache, reference=reference, mixed=mixed_flexible,
        )
        new_sprites += spawned
        if not rec:
            continue
        added.append(rec)
        indexed[("wearable", look)] = rec
        wear_added += 1
        if wear_added % 200 == 0:
            print(f"  doll wear {wear_added}...")

    gear_added = 0
    for (typ, look), group in gear.items():
        # Normal clothes are not doll rows, even when the look number collides.
        rec, spawned = extract_wear_group(
            pd, look, group, doll=None, slot=TYPE_SLOT[typ], component=look,
            obd_items=obd_items, dests=dests, cache=cache, reference=reference, mixed=mixed_flexible,
        )
        new_sprites += spawned
        if not rec:
            continue
        added.append(rec)
        gear_added += 1
        if gear_added % 400 == 0:
            print(f"  gear {gear_added}...")

    if mixed_flexible:
        print(
            f"warning: flexibleHands disagreed inside {len(mixed_flexible)} groups; "
            f"left False unless every row agreed"
        )
    two = sum(1 for rec in added if rec["flags"]["twoHanded"])
    flex = sum(1 for rec in added if rec["flags"]["flexibleHands"])
    print(f"  local flags: twoHanded {two}, flexibleHands {flex}")

    pd["items"].extend(added)
    finish_catalog(pd, reference)
    print(
        f"added {len(added)} groups "
        f"({sum(1 for i in added if i['kind']=='ride')} rides), {new_sprites} new atlases"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retint",
        action="store_true",
        help="Recompute tints from existing PNGs and prune unreferenced sprites. Does not read the client extract.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Attach known ids, prefer English item-table names, retint, and fail if a referenced PNG is missing. Does not read the client extract.",
    )
    args = parser.parse_args()
    if args.repair:
        repair_catalog()
    elif args.retint:
        retint_and_prune()
    else:
        main()
