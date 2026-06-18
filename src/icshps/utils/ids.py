from __future__ import annotations

import hashlib
from pathlib import Path

from icshps.utils.text import normalize_token_text, slugify


def sha256_bytes(data: bytes, *, length: int | None = None) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return digest[:length] if length else digest


def sha256_file(path: Path, *, length: int | None = None) -> str:
    return sha256_bytes(path.read_bytes(), length=length)


def stable_id(prefix: str, *parts: str, length: int = 10) -> str:
    raw = "|".join(normalize_token_text(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def deterministic_name_id(name: str, digest: str, *, length: int = 8) -> str:
    return f"{slugify(name, fallback='bundle')}_{digest[:length]}"
