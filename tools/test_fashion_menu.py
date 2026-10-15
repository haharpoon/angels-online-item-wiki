"""Fashion menu categories against the QA remenu list. No game client required."""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_item_wiki import (  # noqa: E402
    DB,
    FASHION_MENU_KIND,
    ROOT,
    apply_menu_kinds,
    fashion_category,
    load_items,
    load_sprite_layers,
)
from translate_text import translate_item_fields

CSV_PATH = Path(__file__).resolve().parent / "fixtures" / "remenu_moves.csv"


def extra_names() -> dict[str, str]:
    """Other item-table names for the same id, used only when the English name has no keyword."""
    found: dict[str, set[str]] = {}
    con = sqlite3.connect(DB)
    for table in ("item", "item2", "item3", "item4", "item5", "item6", "item7", "item8", "item9"):
        try:
            rows = con.execute(f'select id, "基本名稱", "原型名稱" from {table}')
        except sqlite3.OperationalError:
            continue
        for iid, base, proto in rows:
            bag = found.setdefault(str(iid), set())
            if base:
                bag.add(str(base))
            if proto:
                bag.add(str(proto))
    con.close()
    return {iid: " ".join(sorted(names)) for iid, names in found.items()}


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    if len(rows) != 2674:
        raise SystemExit(f"expected 2674 remenu rows, found {len(rows)}")
    alts = extra_names()
    layers = load_sprite_layers()
    bad = []
    for row in rows:
        iid = int(row["id"])
        got = fashion_category(row["original_name"], alts.get(row["id"], ""), layers.get(iid))
        if got != row["new_category"]:
            bad.append((row["id"], row["original_name"], row["new_category"], got, sorted(layers.get(iid) or [])))
    print(f"remenu rows {len(rows)} matched {len(rows) - len(bad)} missed {len(bad)}")
    for item in bad:
        print(f"  id {item[0]} {item[1]!r} expected {item[2]} got {item[3]} layers={item[4]}")
    # The rows the updated sheet added.
    wanted = {
        23062: "outfits",
        23065: "outfits",
        23089: "outfits",
        23092: "outfits",
        38175: "shoes",
        38177: "shoes",
    }
    by_id = {int(row["id"]): row for row in rows}
    for iid, cat in wanted.items():
        row = by_id[iid]
        if row["new_category"] != cat:
            raise SystemExit(f"{iid} sheet says {row['new_category']}, expected {cat}")
        got = fashion_category(row["original_name"], alts.get(str(iid), ""), layers.get(iid))
        if got != cat:
            raise SystemExit(f"{iid} {row['original_name']} classified {got}, expected {cat}")
    if bad:
        raise SystemExit(f"{len(bad)} remenu rows do not match")
    # Rifles, guns and surfboards are not in the move sheet. They still land on Back.
    for name in ("Tk-18 Rebel War Rifle", "Red Clerk Gun", "Wave-5000 Surfboard 1", "Enchanted- Cutie Surfboard"):
        got = fashion_category(name)
        if got != "back":
            raise SystemExit(f"{name} classified {got}, expected back")
    print("fashion menu ok:", ", ".join(f"{key}={label}" for key, label in FASHION_MENU_KIND.items()))
    catalog = ROOT / "docs" / "pd" / "client_pd_preview.json"
    if catalog.is_file():
        json.loads(catalog.read_text(encoding="utf-8"))
    print(f"sprite layers for {sum(1 for row in rows if layers.get(int(row['id'])))} remenu items")


# The sheet name and the item row disagree, so the page kind follows the row.
# 54580 is 灼熱の兜. The bare-name cache says "The burning bag."; the published
# name is "1 Scorching Helmet", which is a hat. 6351 was Floral Bib in the
# doll catalog; update24 reused the id for a hidden quest flag.
PAGE_EXCEPTIONS = {
    54580: ("Hats", "published name is 1 Scorching Helmet; the sheet name is a bad translation of 兜"),
    6351: ("Hidden", "update24 reused id 6351 for Finish Second Dialogue; the doll catalog still says Floral Bib"),
}


def test_page_build_path() -> None:
    """The kind written into the item page, not fashion_category() alone."""
    items = translate_item_fields(load_items())
    apply_menu_kinds(items)
    built = {item["id"]: item for item in items}
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    bad = []
    for row in rows:
        iid = int(row["id"])
        item = built.get(iid)
        got = None if item is None else item["kind"]
        expect = FASHION_MENU_KIND[row["new_category"]]
        if iid in PAGE_EXCEPTIONS:
            pinned, _why = PAGE_EXCEPTIONS[iid]
            if got != pinned:
                bad.append((iid, row["original_name"], pinned, got, "exception"))
            elif got == expect:
                bad.append((iid, row["original_name"], expect, got, "exception now matches the sheet"))
            continue
        if got != expect:
            bad.append((iid, row["original_name"], expect, got, None if item is None else item["name"]))
    print(f"page build rows {len(rows)} matched {len(rows) - len(bad)} missed {len(bad)}")
    for item in bad:
        print(f"  id {item[0]} {item[1]!r} expected {item[2]} got {item[3]} name={item[4]!r}")
    if bad:
        raise SystemExit(f"{len(bad)} page-build rows do not match")
    bib = built[6351]
    if bib["name"] != "Finish Second Dialogue":
        raise SystemExit(f"6351 name is {bib['name']!r}")
    if "log" in bib["kind"].lower() or bib["kind"] == "Wood":
        raise SystemExit("6351 was classified as Wood because dialogue contains log")
    helmet = built[54580]
    if "Helmet" not in helmet["name"]:
        raise SystemExit(f"54580 name is {helmet['name']!r}")
    print("page build path ok")


if __name__ == "__main__":
    main()
    test_page_build_path()
