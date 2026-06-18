from __future__ import annotations

import re
from typing import Any


def normalize_whitespace(value: str | None) -> str:
    return " ".join((value or "").split())


def normalize_token_text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def normalize_lookup_key(value: str | None) -> str:
    return " ".join((value or "").lower().replace("-", " ").split())


def slugify(value: str | None, *, fallback: str = "unknown") -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    return slug or fallback


def string_list(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        value = raw_value.strip()
        return [value] if value else []

    if not isinstance(raw_value, list):
        return []

    values: list[str] = []

    for item in raw_value:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            value = str(item.get("name") or item.get("label") or "").strip()
        else:
            value = str(item).strip()

        if value:
            values.append(value)

    return values


def optional_float(raw_value: Any) -> float | None:
    if raw_value in (None, ""):
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None