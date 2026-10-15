"""The item-page build keeps integer icon scaling. No game client required."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_item_wiki import (  # noqa: E402
    OUT,
    SHARE,
    assemble_page,
    icon_scaler_gaps,
    require_icon_scaler,
)


def main() -> None:
    page = assemble_page([], {})
    if any(token in page for token in ("__FILES__", "__DATA__", "__GROUPS__", "__SKILLS__")):
        raise SystemExit("assembled page still has a template placeholder")
    require_icon_scaler(page, "assembled template")
    broken = page.replace("function pxIcon", "function dropped", 1)
    gaps = icon_scaler_gaps(broken)
    if "function pxIcon" not in gaps:
        raise SystemExit(f"stripped page was accepted: {gaps}")
    for path in (OUT, SHARE):
        require_icon_scaler(path.read_text(encoding="utf-8"), str(path))
    print("icon scaler ok")


if __name__ == "__main__":
    main()
