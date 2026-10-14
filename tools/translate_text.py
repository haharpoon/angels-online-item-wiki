"""Translate cached client text to English with a local dl-translate model."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "corpus" / "item_translations_en.json"
ASIAN_TEXT = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
HIRAGANA_OR_KATAKANA = re.compile(r"[\u3040-\u30ff]")
HANGUL = re.compile(r"[\uac00-\ud7af]")
TARGET_LANGUAGE = "English"
BATCH_SIZE = 8
_TRANSLATION_MODEL = None


def _load_cache() -> dict[str, str]:
    if not CACHE.is_file():
        return {}
    data = json.loads(CACHE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in data.items()
    ):
        raise ValueError(f"Invalid translation cache: {CACHE}")
    return data


def _save_cache(cache: dict[str, str]) -> None:
    temp = CACHE.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(cache, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    temp.replace(CACHE)


def _source_language(text: str) -> str:
    if HANGUL.search(text):
        return "Korean"
    if HIRAGANA_OR_KATAKANA.search(text):
        return "Japanese"
    return "Chinese"


def _translation_model():
    global _TRANSLATION_MODEL
    if _TRANSLATION_MODEL is None:
        import dl_translate as dlt

        print("Loading local M2M100 translation model (downloaded on first use)...")
        _TRANSLATION_MODEL = dlt.TranslationModel("m2m100", device="auto")
    return _TRANSLATION_MODEL


def _translate_batch(texts: list[str], source_language: str) -> list[str]:
    translations = _translation_model().translate(
        texts,
        source=source_language,
        target=TARGET_LANGUAGE,
        batch_size=BATCH_SIZE,
        verbose=False,
        # dl-translate sets max_new_tokens; avoid conflicting with model max_length.
        generation_options={"max_length": None},
    )
    if not isinstance(translations, list) or len(translations) != len(texts):
        raise RuntimeError(
            f"Local translation returned {len(translations) if isinstance(translations, list) else 'an invalid result'} "
            f"for a batch of {len(texts)} strings"
        )
    if any(not isinstance(value, str) for value in translations):
        raise RuntimeError("Local translation returned a non-text result")
    return [value.strip() for value in translations]


def translate_texts(texts) -> dict[str, str]:
    """Return cached or locally translated English text for each Asian string."""
    texts = list(texts)
    cache = _load_cache()
    pending = sorted({
        text.replace("\r", " ").replace("\n", " ")
        for text in texts
        if isinstance(text, str) and ASIAN_TEXT.search(text)
    } - cache.keys())
    pending_by_language: dict[str, list[str]] = {}
    for text in pending:
        pending_by_language.setdefault(_source_language(text), []).append(text)

    completed = 0
    for source_language, language_texts in pending_by_language.items():
        for start in range(0, len(language_texts), BATCH_SIZE):
            batch = language_texts[start:start + BATCH_SIZE]
            translations = _translate_batch(batch, source_language)
            cache.update(zip(batch, translations))
            completed += len(batch)
            _save_cache(cache)
            print(
                f"Translated or cached {len(cache)} strings; "
                f"{len(pending) - completed} remaining."
            )
    return {
        text: cache[text.replace("\r", " ").replace("\n", " ")]
        for text in texts
        if isinstance(text, str) and ASIAN_TEXT.search(text)
    }


def translate_item_fields(items: list[dict]) -> list[dict]:
    fields = ("name", "desc", "prefix", "raw")
    translations = translate_texts(
        item[field] for item in items for field in fields if item.get(field)
    )
    for item in items:
        for field in fields:
            value = item.get(field)
            if value in translations:
                item[field] = translations[value]
    return items


def translate_catalog_display_text(catalog: dict) -> None:
    strings: list[str] = []
    for item in catalog.get("items", []):
        for field in ("name", "collectionRaw"):
            value = item.get(field)
            if isinstance(value, str):
                strings.append(value)
        aliases = item.get("aliases", [])
        if isinstance(aliases, list):
            strings.extend(value for value in aliases if isinstance(value, str))

    metadata = catalog.get("metadata", {}).get("filters", {})
    if isinstance(metadata, dict):
        for values in metadata.values():
            if isinstance(values, list):
                strings.extend(value for value in values if isinstance(value, str))

    translations = translate_texts(strings)
    for item in catalog.get("items", []):
        for field in ("name", "collectionRaw"):
            value = item.get(field)
            if value in translations:
                item[field] = translations[value]
        aliases = item.get("aliases", [])
        if isinstance(aliases, list):
            item["aliases"] = [translations.get(value, value) for value in aliases]

    if isinstance(metadata, dict):
        for key, values in metadata.items():
            if isinstance(values, list):
                metadata[key] = [translations.get(value, value) for value in values]
