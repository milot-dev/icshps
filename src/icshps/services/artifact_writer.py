from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from icshps.schemas.run import ArtifactStatus, RunArtifactManifest
from icshps.services.run_scaffolding import RunScaffold
from icshps.utils.file_io import read_json_object, write_json


def artifact_path(scaffold: RunScaffold, artifact_key: str) -> Path:
    """Return the reserved filesystem path for one artifact manifest key."""

    manifest = RunArtifactManifest.model_validate(
        read_json_object(scaffold.artifact_manifest_path)
    )

    if artifact_key not in manifest.artifacts:
        raise KeyError(f"Unknown artifact manifest key: {artifact_key}")

    artifact_ref = manifest.artifacts[artifact_key]
    return scaffold.run_dir / artifact_ref.path


def write_json_artifact(
    *,
    scaffold: RunScaffold,
    artifact_key: str,
    payload: BaseModel | dict[str, Any],
    mark_created: bool = True,
) -> Path:
    """Write a JSON artifact and optionally mark it as created in the manifest."""

    path = artifact_path(scaffold, artifact_key)
    write_json(path, payload)

    if mark_created:
        mark_artifacts_created(scaffold=scaffold, artifact_keys=(artifact_key,))

    return path


def read_json_artifact(
    *,
    scaffold: RunScaffold,
    artifact_key: str,
) -> dict[str, Any] | None:
    """Read a JSON artifact if its reserved file exists; otherwise return None."""

    path = artifact_path(scaffold, artifact_key)
    if not path.exists():
        return None

    return read_json_object(path)


def mark_artifacts_created(
    *,
    scaffold: RunScaffold,
    artifact_keys: tuple[str, ...],
) -> None:
    """Mark one or more reserved artifacts as created in artifact_manifest.json."""

    manifest = RunArtifactManifest.model_validate(
        read_json_object(scaffold.artifact_manifest_path)
    )
    artifacts = dict(manifest.artifacts)

    for key in artifact_keys:
        if key not in artifacts:
            raise KeyError(f"Unknown artifact manifest key: {key}")

        artifacts[key] = artifacts[key].model_copy(
            update={"status": ArtifactStatus.CREATED}
        )

    write_json(
        scaffold.artifact_manifest_path,
        manifest.model_copy(update={"artifacts": artifacts}),
    )
