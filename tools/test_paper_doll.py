"""Paper-doll mapping, two-handed flags, and atlas rejection. No game client required."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ewsp import is_placeholder_size, pack_atlas
from extract_local_pd import (
    CATALOG,
    DB,
    SKIN_TOLERANCE,
    TYPE_SLOT,
    choose_display_name,
    choose_tint,
    classify_local_item,
    derive_flexible,
    derive_two_handed,
    load_dolls,
    shadow_sheet_ids,
)
from report_shapeshift import REPORT, collect_shapeshift_candidates, render_report

ROOT = Path(__file__).resolve().parents[1]


def test_shadow_sheets():
    assert shadow_sheet_ids({70038, 75038}) == {75038}
    assert shadow_sheet_ids({70955, 75955}) == {75955}
    assert shadow_sheet_ids({21212, 26212}) == {26212}
    assert shadow_sheet_ids({70171}) == set()
    assert 120123 in shadow_sheet_ids({120123, 80})
    assert 80 not in shadow_sheet_ids({120123, 80})


def test_wrong_slot_examples_are_not_doll_rows():
    """Look ids that collide with the doll table stay on the item's own slot."""
    dolls = set(load_dolls(DB))
    cases = [
        (61, "衣服", 264, "gear", "body"),
        (141, "頭飾", 31, "gear", "head"),
        (174, "盾", 424, "gear", "off"),
        (381, "鞋子", 115, "gear", "feet"),
        (1755, "衣服", 1083, "gear", "body"),
        (4128, "鞋子", 1615, "gear", "feet"),
        (6551, "紙娃娃", 260, "doll", None),
        (7248, "座騎", 264, "mount", None),
    ]
    con = sqlite3.connect(DB)
    for iid, typ, look, bucket, slot in cases:
        row = None
        for table in ["item", *[f"item{i}" for i in range(2, 10)]]:
            row = con.execute(
                f'select "物品類別", "原型外觀" from {table} where id=?', (str(iid),)
            ).fetchone()
            if row:
                break
        assert row is not None, iid
        assert row[0] == typ and int(float(row[1])) == look
        it = {"id": iid, "type": typ, "look": look}
        assert classify_local_item(it, dolls) == bucket, (iid, bucket)
        if bucket == "gear":
            assert TYPE_SLOT[typ] == slot
            # The colliding doll row occupies a different slot. Novice Costume is
            # body armour, not doll 264's Aladdin boots.
            doll = load_dolls(DB)[look]
            assert slot not in doll["parts"]


def test_two_handed_matches_the_existing_seventeen():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    dolls = load_dolls(DB)
    flagged = []
    predicted = []
    for rec in catalog["items"]:
        if "main" not in (rec.get("componentIds") or {}):
            continue
        look = int(rec["appearanceIds"][0])
        doll = dolls.get(look)
        # The seventeen have no L sheet in the catalog.
        has_l = any(
            str(key).endswith("l") or str(key).endswith("l-mounted")
            for sex in (rec.get("components") or {}).values()
            for pose in sex.values()
            for key in pose.values()
        )
        two = derive_two_handed(
            slot="main",
            types={"紙娃娃"},
            right_flags=[True],
            left_flags=[bool(rec["flags"].get("flexibleHands"))],
            has_l_sprite=has_l,
            doll=doll,
        )
        # Chainsaw is both-hands in the item table and has no L sheet.
        if rec["item_id"] == 9697:
            two = derive_two_handed(
                slot="main",
                types={"紙娃娃"},
                right_flags=[True],
                left_flags=[True],
                has_l_sprite=False,
                doll=doll,
            )
        if rec["flags"].get("twoHanded"):
            flagged.append(rec["item_id"])
        if two:
            predicted.append(rec["item_id"])
    assert len(flagged) == 17, flagged
    assert set(predicted) == set(flagged)


def test_flexible_needs_an_l_sheet():
    assert derive_flexible(
        slot="main", two_handed=False, right_flags=[True], left_flags=[True], has_l_sprite=True,
    )
    assert not derive_flexible(
        slot="main", two_handed=True, right_flags=[True], left_flags=[True], has_l_sprite=True,
    )
    assert not derive_flexible(
        slot="main", two_handed=False, right_flags=[True], left_flags=[True], has_l_sprite=False,
    )
    assert not derive_flexible(
        slot="off", two_handed=False, right_flags=[True], left_flags=[True], has_l_sprite=True,
    )
    assert derive_two_handed(
        slot="main", types={"弓箭"}, right_flags=[True], left_flags=[False],
        has_l_sprite=False, doll=None,
    )
    assert not derive_two_handed(
        slot="main", types={"弓箭"}, right_flags=[True, True], left_flags=[True, True],
        has_l_sprite=True, doll=None,
    )
    assert not derive_two_handed(
        slot="off", types={"盾"}, right_flags=[False], left_flags=[True],
        has_l_sprite=False, doll=None,
    )


def test_english_name_preference():
    name, aliases = choose_display_name(["男雛ウェア緋", "The Boy Wire.", "The Boy Wire."])
    assert name == "The Boy Wire."
    assert aliases[0] == "The Boy Wire."
    name, _aliases = choose_display_name(["深淵惡魔戰甲"])
    assert name == "深淵惡魔戰甲"


def test_tint_defaults():
    assert SKIN_TOLERANCE <= 40
    assert choose_tint("weapon", 500) == "none"
    assert choose_tint("ride", 500) == "none"
    assert choose_tint("wear", 0) == "none"
    assert choose_tint("wear", 12) == "skin"
    assert choose_tint("base", 0) == "skin"
    assert choose_tint("hair", 0) == "hair"


def test_shapeshift_dolls_replace_the_character():
    """變身換圖 is a full-character sprite. A clothing doll and a colliding ride are not."""
    dolls = load_dolls(DB)
    melon = dolls[250]
    assert melon["shapeshift"] is True
    assert melon["parts"] == {"body": 1886}
    assert dolls[264]["shapeshift"] is False
    assert sum(1 for doll in dolls.values() if doll.get("shapeshift")) == 294
    rows = collect_shapeshift_candidates()
    by_id = {row["id"]: row for row in rows}
    assert len(rows) == len(by_id) == 467
    assert by_id[6308]["category"] == "Shapeshift"
    assert by_id[6308]["doll_id"] == 250
    assert by_id[3891]["category"] == "Fashion"
    assert by_id[6390]["category"] == "Outfits"
    assert 61 not in by_id
    assert 8310 not in by_id
    assert REPORT.read_text(encoding="utf-8") == render_report(rows)


def test_pack_atlas_rejects_gaps_and_placeholders():
    partial = [{"index": i, "width": 8, "height": 8} for i in range(14)]
    assert pack_atlas(partial) is None
    placeholder = [{"index": i, "width": 800, "height": 600} for i in range(15)]
    assert pack_atlas(placeholder) is None
    assert is_placeholder_size(800, 600)
    assert is_placeholder_size(4000, 1800)
    assert not is_placeholder_size(86, 82)


if __name__ == "__main__":
    test_shadow_sheets()
    test_wrong_slot_examples_are_not_doll_rows()
    test_two_handed_matches_the_existing_seventeen()
    test_flexible_needs_an_l_sheet()
    test_english_name_preference()
    test_tint_defaults()
    test_shapeshift_dolls_replace_the_character()
    test_pack_atlas_rejects_gaps_and_placeholders()
    print("ok")
