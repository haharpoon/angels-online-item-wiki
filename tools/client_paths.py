"""Client asset path configuration shared by the build tools."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configured_extract() -> Path | None:
    """Return AO_EXTRACT from the environment or project env files."""
    value = os.environ.get("AO_EXTRACT", "").strip()
    if not value:
        for env_file in (ROOT / ".env.local", ROOT / ".env"):
            if not env_file.is_file():
                continue
            for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, file_value = line.split("=", 1)
                if key.strip() != "AO_EXTRACT":
                    continue
                file_value = file_value.strip()
                if len(file_value) >= 2 and file_value[0] == file_value[-1] and file_value[0] in ("'", '"'):
                    file_value = file_value[1:-1]
                value = file_value
                break
            if value:
                break
    return Path(value).expanduser() if value else None
