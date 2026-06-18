from __future__ import annotations

import re
from typing import Any, Iterable


MULTILANG_KEYS = (
    "uz",
    "cyrl",
    "ru",
    "en",
    "title_uz",
    "title_uzk",
    "title_ru",
    "title_en",
    "title",
    "name",
    "value",
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").replace("\u00a0", " ").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    return " ".join(text.split())


def pick_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in MULTILANG_KEYS:
            raw_current = value.get(key)
            current = pick_text(raw_current) if isinstance(raw_current, (dict, list, tuple, set)) else clean_text(raw_current)
            if current:
                return current
        for current in value.values():
            text = pick_text(current)
            if text:
                return text
        return ""
    if isinstance(value, (list, tuple, set)):
        items = [pick_text(item) for item in value]
        return join_non_empty(items, sep=", ")
    return clean_text(value)


def maybe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = clean_text(value)
    if not text:
        return None
    try:
        return int(float(text.replace(",", ".")))
    except Exception:
        return None


def maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(value)
    if not text:
        return None
    normalized = text.replace(" ", "").replace("\u202f", "").replace(",", ".")
    try:
        return float(normalized)
    except Exception:
        return None


def join_non_empty(values: Iterable[Any], *, sep: str = " | ") -> str:
    parts = [clean_text(value) for value in values if clean_text(value)]
    return sep.join(parts)


def build_parameter_text(pairs: Iterable[tuple[str, Any]], *, sep: str = " | ") -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for label, value in pairs:
        text = pick_text(value)
        if not text:
            continue
        item = f"{clean_text(label)}: {text}" if clean_text(label) else text
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(item)
    return sep.join(parts)


def build_properties_text(properties: Any, *, sep: str = " | ") -> str:
    if not isinstance(properties, list):
        return ""

    pairs: list[tuple[str, Any]] = []
    for item in properties:
        if not isinstance(item, dict):
            continue

        label = (
            pick_text(item.get("prop_name"))
            or pick_text(item.get("title"))
            or pick_text(item.get("title_uz"))
            or pick_text(item.get("name"))
            or pick_text(item.get("property_name"))
        )
        value = (
            pick_text(item.get("val_name"))
            or pick_text(item.get("option"))
            or pick_text(item.get("option_uz"))
            or pick_text(item.get("value"))
            or pick_text(item.get("field_value"))
            or pick_text(item.get("value_name"))
        )
        if not value and item.get("val_numb") not in {None, ""}:
            value = pick_text(item.get("val_numb"))
        if label and value:
            pairs.append((label, value))

    return build_parameter_text(pairs, sep=sep)


def find_property_value(properties: Any, keywords: Iterable[str]) -> str:
    if not isinstance(properties, list):
        return ""

    normalized_keywords = [clean_text(keyword).lower() for keyword in keywords if clean_text(keyword)]
    for item in properties:
        if not isinstance(item, dict):
            continue
        label = (
            pick_text(item.get("prop_name"))
            or pick_text(item.get("title"))
            or pick_text(item.get("title_uz"))
            or pick_text(item.get("name"))
            or pick_text(item.get("property_name"))
        ).lower()
        if not label or not any(keyword in label for keyword in normalized_keywords):
            continue
        value = (
            pick_text(item.get("val_name"))
            or pick_text(item.get("option"))
            or pick_text(item.get("option_uz"))
            or pick_text(item.get("value"))
            or pick_text(item.get("field_value"))
            or pick_text(item.get("value_name"))
        )
        if value:
            return value
    return ""


def build_raw_text(pairs: Iterable[tuple[str, Any]]) -> str:
    lines: list[str] = []
    for label, value in pairs:
        text = pick_text(value)
        if text:
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


def pick_region_name(value: Any) -> str | None:
    text = pick_text(value)
    return text or None


def area_path_to_text(area_path: Any) -> str | None:
    if not isinstance(area_path, list):
        return None
    values = [pick_text(item.get("name") if isinstance(item, dict) else item) for item in area_path]
    text = join_non_empty(values, sep=", ")
    return text or None
