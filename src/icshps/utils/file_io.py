from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

JsonPayload = BaseModel | dict[str, Any] | list[Any]


def read_json_object(path: Path, *, default_empty: bool = False) -> dict[str, Any]:
    if default_empty and not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object at {path}")

    return raw


def write_json(path: Path, payload: JsonPayload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    data = (
        payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    )

    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_yaml_object(
    path: Path | None, *, default_empty: bool = True
) -> dict[str, Any]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        if default_empty:
            return {}
        raise FileNotFoundError(f"Missing YAML file: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    if not isinstance(raw, dict):
        return {}

    return raw


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, sort_keys=True) + "\n")
