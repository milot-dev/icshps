from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from icshps.schemas.common import EvidenceRef
from icshps.schemas.context import BundleContext
from icshps.schemas.manifest import HiringBundleManifest
from icshps.services.run_scaffolding import RunScaffold

MANIFEST_FILENAME = "manifest.yaml"


@dataclass(frozen=True)
class LoadedBundle:
    """Controlled result returned by the Hiring Bundle loader."""

    bundle_path: Path
    manifest_path: Path
    manifest: HiringBundleManifest | None
    context: BundleContext | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and self.context is not None


def load_hiring_bundle(bundle_path: str | Path, *, run_id: str) -> LoadedBundle:
    """
    Load and validate one Hiring Bundle from disk.

    The loader is intentionally deterministic and side-effect free:
    it reads manifest.yaml, validates the contract, resolves paths, checks
    file existence, and returns a BundleContext for Application Intake / Context Agent.
    """

    resolved_bundle_path = Path(bundle_path).resolve()
    manifest_path = resolved_bundle_path / MANIFEST_FILENAME
    warnings: list[str] = []
    errors: list[str] = []

    if not resolved_bundle_path.exists():
        return _failed_result(
            bundle_path=resolved_bundle_path,
            manifest_path=manifest_path,
            error=f"Hiring Bundle path does not exist: {resolved_bundle_path}",
        )

    if not resolved_bundle_path.is_dir():
        return _failed_result(
            bundle_path=resolved_bundle_path,
            manifest_path=manifest_path,
            error=f"Hiring Bundle path is not a directory: {resolved_bundle_path}",
        )

    if not manifest_path.exists():
        return _failed_result(
            bundle_path=resolved_bundle_path,
            manifest_path=manifest_path,
            error=f"Missing required manifest file: {manifest_path}",
        )

    try:
        raw_manifest = _read_yaml_mapping(manifest_path)
    except ValueError as exc:
        return _failed_result(
            bundle_path=resolved_bundle_path,
            manifest_path=manifest_path,
            error=str(exc),
        )

    try:
        manifest = HiringBundleManifest.model_validate(raw_manifest)
    except ValidationError as exc:
        return _failed_result(
            bundle_path=resolved_bundle_path,
            manifest_path=manifest_path,
            error=f"Invalid manifest.yaml contract: {exc}",
        )

    resolved_manifest = _resolve_manifest_paths(
        manifest=manifest,
        bundle_path=resolved_bundle_path,
    )

    _validate_required_inputs(
        manifest=resolved_manifest,
        errors=errors,
    )
    _validate_candidate_resumes(
        manifest=resolved_manifest,
        errors=errors,
    )
    _validate_optional_inputs(
        manifest=resolved_manifest,
        warnings=warnings,
        errors=errors,
    )

    evidence_index = _build_initial_evidence_index(resolved_manifest)

    context = BundleContext(
        run_id=run_id,
        bundle_path=resolved_bundle_path,
        bundle=resolved_manifest.bundle,
        scenario=resolved_manifest.scenario,
        job=resolved_manifest.job,
        candidates=resolved_manifest.candidates,
        required_inputs=resolved_manifest.required_inputs,
        optional_inputs=resolved_manifest.optional_inputs,
        evidence_index=evidence_index,
        validation_warnings=warnings,
        validation_errors=errors,
        is_ready=not errors,
    )

    return LoadedBundle(
        bundle_path=resolved_bundle_path,
        manifest_path=manifest_path,
        manifest=resolved_manifest,
        context=context,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def snapshot_manifest_to_run(bundle_path: str | Path, scaffold: RunScaffold) -> Path:
    """Copy manifest.yaml into the run inputs directory for auditability."""

    manifest_path = Path(bundle_path).resolve() / MANIFEST_FILENAME

    if not manifest_path.exists():
        raise FileNotFoundError(f"Cannot snapshot missing manifest: {manifest_path}")

    destination = scaffold.inputs_dir / "manifest_snapshot.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_path, destination)

    return destination


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file and ensure the top-level value is a mapping."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML syntax in {path}: {exc}") from exc

    if raw is None:
        raise ValueError(f"Manifest file is empty: {path}")

    if not isinstance(raw, dict):
        raise ValueError(f"Manifest root must be a YAML mapping/object: {path}")

    return raw


def _resolve_manifest_paths(
    *,
    manifest: HiringBundleManifest,
    bundle_path: Path,
) -> HiringBundleManifest:
    """Return a manifest copy where all file paths are absolute paths."""

    return manifest.model_copy(
        update={
            "candidates": [
                candidate.model_copy(
                    update={
                        "resume_file": _resolve_bundle_path(
                            bundle_path,
                            candidate.resume_file,
                        )
                    }
                )
                for candidate in manifest.candidates
            ],
            "required_inputs": manifest.required_inputs.model_copy(
                update={
                    field_name: _resolve_bundle_path(bundle_path, field_value)
                    for field_name, field_value in manifest.required_inputs
                }
            ),
            "optional_inputs": manifest.optional_inputs.model_copy(
                update={
                    field_name: _resolve_bundle_path(bundle_path, field_value)
                    if field_value is not None
                    else None
                    for field_name, field_value in manifest.optional_inputs
                }
            ),
        }
    )


def _resolve_bundle_path(bundle_path: Path, value: Path) -> Path:
    """Resolve a manifest path relative to the Hiring Bundle root."""

    if value.is_absolute():
        return value.resolve()

    return (bundle_path / value).resolve()


def _validate_required_inputs(
    *,
    manifest: HiringBundleManifest,
    errors: list[str],
) -> None:
    """Validate required input files declared by manifest.required_inputs."""

    for field_name, file_path in manifest.required_inputs:
        _require_file(
            file_path,
            errors,
            label=f"required_inputs.{field_name}",
        )


def _validate_candidate_resumes(
    *,
    manifest: HiringBundleManifest,
    errors: list[str],
) -> None:
    """Validate candidate resume files listed in the manifest."""

    seen_application_ids: set[str] = set()

    for candidate in manifest.candidates:
        if candidate.application_id in seen_application_ids:
            errors.append(
                f"Duplicate candidate application_id in manifest: {candidate.application_id}"
            )
        seen_application_ids.add(candidate.application_id)

        _require_file(
            candidate.resume_file,
            errors,
            label=f"candidates[{candidate.id}].resume_file",
        )

        if candidate.resume_file.suffix.lower() != ".pdf":
            errors.append(
                f"Candidate resume must be a clean PDF for Sprint 1: {candidate.resume_file}"
            )


def _validate_optional_inputs(
    *,
    manifest: HiringBundleManifest,
    warnings: list[str],
    errors: list[str],
) -> None:
    """Validate optional inputs only when they are referenced."""

    for field_name, file_path in manifest.optional_inputs:
        if file_path is None:
            continue

        if file_path.exists() and file_path.is_file():
            continue

        message = (
            "Optional input was declared but file is missing: "
            f"optional_inputs.{field_name} -> {file_path}"
        )

        if manifest.execution.allow_missing_optional_inputs:
            warnings.append(message)
        else:
            errors.append(message)


def _require_file(path: Path, errors: list[str], *, label: str) -> None:
    """Append a controlled error when a required file is missing."""

    if not path.exists():
        errors.append(f"Missing {label}: {path}")
        return

    if not path.is_file():
        errors.append(f"Expected {label} to be a file: {path}")


def _build_initial_evidence_index(manifest: HiringBundleManifest) -> list[EvidenceRef]:
    """Create source-level evidence references for files known at intake time."""

    evidence: list[EvidenceRef] = []

    for candidate in manifest.candidates:
        evidence.append(
            EvidenceRef(
                source_path=candidate.resume_file,
                source_type="resume_pdf",
                section="candidate_resume",
                confidence=1.0,
            )
        )

    required_source_types = {
        "job_description": "job_description",
        "skills_matrix": "skills_matrix",
        "eeo_policy": "policy",
        "credential_rules": "policy",
        "hris_master": "mock_data",
    }

    for field_name, file_path in manifest.required_inputs:
        evidence.append(
            EvidenceRef(
                source_path=file_path,
                source_type=required_source_types.get(field_name, "required_input"),
                section=field_name,
                confidence=1.0,
            )
        )

    return evidence


def _failed_result(
    *,
    bundle_path: Path,
    manifest_path: Path,
    error: str,
) -> LoadedBundle:
    return LoadedBundle(
        bundle_path=bundle_path,
        manifest_path=manifest_path,
        manifest=None,
        context=None,
        warnings=(),
        errors=(error,),
    )
