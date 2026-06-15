from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from icshps.schemas.run import RunArtifactManifest

ArtifactAvailabilityStatus = Literal["available", "not_generated_yet"]
ArtifactCatalogStatus = Literal[
    "ready",
    "missing_run_directory",
    "missing_manifest",
    "invalid_manifest",
]


@dataclass(frozen=True)
class ArtifactCatalogItem:
    """Display-safe readiness information for one expected run artifact."""

    key: str
    filename: str
    relative_path: Path
    absolute_path: Path
    owner: str
    description: str
    required_for_mvp: bool
    status: ArtifactAvailabilityStatus

    @property
    def is_available(self) -> bool:
        """Return True when the expected artifact file exists on disk."""

        return self.status == "available"

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly row for UI or orchestration consumers."""

        return {
            "key": self.key,
            "filename": self.filename,
            "relative_path": self.relative_path.as_posix(),
            "absolute_path": str(self.absolute_path),
            "owner": self.owner,
            "description": self.description,
            "required_for_mvp": self.required_for_mvp,
            "status": self.status,
        }


@dataclass(frozen=True)
class ArtifactCatalogResult:
    """Controlled service result for artifact discovery in one run directory."""

    status: ArtifactCatalogStatus
    run_id: str | None
    run_dir: Path
    manifest_path: Path
    artifacts: tuple[ArtifactCatalogItem, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Return True when artifact discovery completed successfully."""

        return self.status == "ready"

    def as_dict(self) -> dict[str, Any]:
        """Return deterministic, JSON-friendly catalog data."""

        return {
            "status": self.status,
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "manifest_path": str(self.manifest_path),
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "errors": list(self.errors),
        }


def read_artifact_catalog(run_dir: str | Path) -> ArtifactCatalogResult:
    """
    Read artifact_manifest.json and report artifact availability for a run.

    This service never fails because an expected artifact is missing. Missing
    artifacts are returned with status "not_generated_yet" so the Streamlit
    layer can display a safe placeholder instead of crashing.
    """

    resolved_run_dir = Path(run_dir).expanduser().resolve()
    manifest_path = resolved_run_dir / "artifact_manifest.json"

    if not resolved_run_dir.exists() or not resolved_run_dir.is_dir():
        return ArtifactCatalogResult(
            status="missing_run_directory",
            run_id=None,
            run_dir=resolved_run_dir,
            manifest_path=manifest_path,
            artifacts=(),
            errors=(f"Run directory does not exist: {resolved_run_dir}",),
        )

    if not manifest_path.exists():
        return ArtifactCatalogResult(
            status="missing_manifest",
            run_id=resolved_run_dir.name,
            run_dir=resolved_run_dir,
            manifest_path=manifest_path,
            artifacts=(),
            errors=(f"Missing artifact manifest: {manifest_path}",),
        )

    try:
        manifest = RunArtifactManifest.model_validate(_read_json_object(manifest_path))
        artifacts = tuple(
            _build_catalog_item(
                run_dir=resolved_run_dir,
                key=key,
                manifest=manifest,
            )
            for key in sorted(manifest.artifacts)
        )
    except (json.JSONDecodeError, OSError, TypeError, ValueError, ValidationError) as exc:
        return ArtifactCatalogResult(
            status="invalid_manifest",
            run_id=resolved_run_dir.name,
            run_dir=resolved_run_dir,
            manifest_path=manifest_path,
            artifacts=(),
            errors=(f"Invalid artifact manifest at {manifest_path}: {exc}",),
        )

    return ArtifactCatalogResult(
        status="ready",
        run_id=manifest.run_id,
        run_dir=resolved_run_dir,
        manifest_path=manifest_path,
        artifacts=artifacts,
    )


def _build_catalog_item(
    *,
    run_dir: Path,
    key: str,
    manifest: RunArtifactManifest,
) -> ArtifactCatalogItem:
    artifact_ref = manifest.artifacts[key]
    relative_path = _normalize_relative_path(artifact_ref.path)
    absolute_path = _resolve_inside_run_dir(run_dir=run_dir, relative_path=relative_path)

    status: ArtifactAvailabilityStatus = (
        "available"
        if absolute_path.exists() and absolute_path.is_file()
        else "not_generated_yet"
    )

    return ArtifactCatalogItem(
        key=key,
        filename=relative_path.name,
        relative_path=relative_path,
        absolute_path=absolute_path,
        owner=artifact_ref.owner,
        description=artifact_ref.description,
        required_for_mvp=artifact_ref.required_for_mvp,
        status=status,
    )


def _normalize_relative_path(path: Path) -> Path:
    """Normalize manifest paths so Windows-written manifests work cross-platform."""

    raw_path = path.as_posix().replace("\\", "/")
    parts = [part for part in raw_path.split("/") if part not in {"", "."}]

    if not parts:
        raise ValueError("Artifact path cannot be empty")

    normalized = Path(*parts)

    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"Artifact paths must stay inside the run directory: {path}")

    return normalized


def _resolve_inside_run_dir(*, run_dir: Path, relative_path: Path) -> Path:
    """Resolve an artifact path and reject paths outside the run directory."""

    absolute_path = (run_dir / relative_path).resolve()

    if not absolute_path.is_relative_to(run_dir):
        raise ValueError(f"Artifact path escapes run directory: {relative_path}")

    return absolute_path


def _read_json_object(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object at {path}")

    return raw