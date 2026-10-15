"""List paper-doll items whose sprite replaces the whole character.

The doll column 變身換圖 marks a body component that stands in for the character,
not a clothing layer. This does not change item categories. A person reviews
the rows whose current category is not already Shapeshift.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from extract_local_pd import DB, ITEM_TABLES, load_dolls

ROOT = Path(__file__).resolve().parents[1]
WIKI_HTML = ROOT / "docs" / "items.html"
REPORT = ROOT / "docs" / "pd" / "shapeshift-candidates.md"


def wiki_items(path: Path = WIKI_HTML) -> dict[int, dict]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"const DATA = (\[.*\]);\n", text)
    if not match:
        raise SystemExit(f"no item DATA in {path}")
    return {int(row["id"]): row for row in json.loads(match.group(1))}


def collect_shapeshift_candidates(db: Path = DB, wiki_html: Path = WIKI_HTML) -> list[dict]:
    dolls = load_dolls(db)
    shift = {did: doll for did, doll in dolls.items() if doll.get("shapeshift")}
    wiki = wiki_items(wiki_html)
    con = sqlite3.connect(db)
    found: dict[int, int] = {}
    for table in ITEM_TABLES:
        if not con.execute(
            "select 1 from sqlite_master where type='table' and name=?", (table,)
        ).fetchone():
            continue
        rows = con.execute(
            f'select "id", "原型外觀" from {table} where "物品類別"=?',
            ("紙娃娃",),
        )
        for iid, look in rows:
            try:
                item_id = int(iid)
                doll_id = int(float(look))
            except (TypeError, ValueError):
                continue
            if doll_id not in shift or item_id in found:
                continue
            found[item_id] = doll_id
    out = []
    for item_id in sorted(found):
        doll_id = found[item_id]
        doll = shift[doll_id]
        page = wiki.get(item_id) or {}
        name = str(page.get("name") or item_id)
        category = str(page.get("kind") or "not on the item page")
        body = (doll.get("parts") or {}).get("body")
        out.append({
            "id": item_id,
            "name": name,
            "category": category,
            "doll_id": doll_id,
            "body": body,
            "reason": (
                f"Doll {doll_id} body component {body} is marked 變身換圖. "
                "That sprite replaces the whole character instead of a clothing layer."
            ),
        })
    return out


def render_report(rows: list[dict]) -> str:
    counts = Counter(row["category"] for row in rows)
    already = counts.get("Shapeshift", 0)
    lines = [
        "# Shapeshift candidates",
        "",
        "These paper-doll items use a doll row marked `變身換圖`. The body component is a full character sprite, not a hat, coat, or other single clothing layer. Categories are left as they are.",
        "",
        f"{len(rows)} items. {already} are already Shapeshift. {len(rows) - already} are filed under another category for a person to confirm.",
        "",
        "| category | items |",
        "| --- | ---: |",
    ]
    for category, count in counts.most_common():
        lines.append(f"| {category} | {count} |")
    lines.extend([
        "",
        "| id | name | category | reason |",
        "| --- | --- | --- | --- |",
    ])
    for row in rows:
        name = row["name"].replace("|", "\\|").replace("\n", " ")
        reason = row["reason"].replace("|", "\\|")
        lines.append(
            f"| {row['id']} | {name} | {row['category']} | {reason} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    rows = collect_shapeshift_candidates()
    text = render_report(rows)
    REPORT.write_text(text, encoding="utf-8")
    print(f"wrote {REPORT} ({len(rows)} items)")


if __name__ == "__main__":
    main()
