from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from icshps.schemas.run import (
    ArtifactRef,
    ArtifactStatus,
    RunArtifactManifest,
    RunMetadata,
)
from icshps.utils.file_io import append_jsonl, write_json, write_text
from icshps.utils.ids import deterministic_name_id


V2_METRIC_DEFAULTS: dict[str, Any] = {
    "llm_enabled": False,
    "llm_provider_used": None,
    "llm_resume_extraction_calls": 0,
    "local_llm_fallback_used": False,
    "scanned_resume_detected_count": 0,
    "interview_schedule_items_created": 0,
    "fraud_findings_count": 0,
    "ats_mock_records_loaded": 0,
}


@dataclass(frozen=True)
class RunScaffold:
    """Convenience object containing important paths for one run."""

    run_id: str
    run_dir: Path
    inputs_dir: Path
    artifacts_dir: Path
    logs_dir: Path
    tmp_dir: Path

    @property
    def metadata_path(self) -> Path:
        return self.run_dir / "run_metadata.json"

    @property
    def artifact_manifest_path(self) -> Path:
        return self.run_dir / "artifact_manifest.json"


def prepare_run_scaffold(
    bundle_path: Path,
    runs_root: Path = Path("runs"),
    run_id: str | None = None,
    reset: bool = True,
) -> RunScaffold:
    """
    Create the deterministic runs/<run_id>/ folder structure.

    This function does not parse the Hiring Bundle manifest.
    Bundle parsing belongs to Task 5: Hiring Bundle Loader and Validation.
    """

    bundle_path = bundle_path.resolve()
    runs_root = runs_root.resolve()

    if not bundle_path.exists():
        raise FileNotFoundError(f"Hiring Bundle path does not exist: {bundle_path}")

    input_fingerprint = compute_bundle_fingerprint(bundle_path)
    resolved_run_id = run_id or build_deterministic_run_id(
        bundle_name=bundle_path.name,
        input_fingerprint=input_fingerprint,
    )

    run_dir = runs_root / resolved_run_id

    if reset:
        _safe_reset_run_dir(run_dir=run_dir, runs_root=runs_root)

    scaffold = RunScaffold(
        run_id=resolved_run_id,
        run_dir=run_dir,
        inputs_dir=run_dir / "inputs",
        artifacts_dir=run_dir / "artifacts",
        logs_dir=run_dir / "logs",
        tmp_dir=run_dir / "tmp",
    )

    _create_directories(scaffold)

    metadata = RunMetadata(
        run_id=scaffold.run_id,
        bundle_path=bundle_path,
        run_dir=scaffold.run_dir,
        input_fingerprint=input_fingerprint,
    )

    artifact_manifest = build_artifact_manifest(scaffold)

    write_json(scaffold.metadata_path, metadata)
    write_json(scaffold.artifact_manifest_path, artifact_manifest)

    write_text(
        scaffold.artifacts_dir / "audit_log.md",
        build_initial_audit_log(scaffold),
    )

    write_json(
        scaffold.artifacts_dir / "metrics.json",
        build_initial_metrics(scaffold),
    )

    append_jsonl(
        scaffold.logs_dir / "audit_events.jsonl",
        {
            "event": "run_scaffold_created",
            "run_id": scaffold.run_id,
            "status": "created",
        },
    )

    return scaffold


def compute_bundle_fingerprint(bundle_path: Path) -> str:
    """
    Compute a stable hash from files inside the Hiring Bundle.

    This keeps run IDs deterministic for the same bundle contents.
    """

    hasher = hashlib.sha256()

    files = sorted(path for path in bundle_path.rglob("*") if path.is_file())

    if not files:
        hasher.update(bundle_path.name.encode("utf-8"))
        return hasher.hexdigest()

    for file_path in files:
        relative_path = file_path.relative_to(bundle_path).as_posix()
        hasher.update(relative_path.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(file_path.read_bytes())
        hasher.update(b"\0")

    return hasher.hexdigest()


def build_deterministic_run_id(bundle_name: str, input_fingerprint: str) -> str:
    """Build a readable and stable run ID."""

    return deterministic_name_id(bundle_name, input_fingerprint)


def build_artifact_manifest(scaffold: RunScaffold) -> RunArtifactManifest:
    """Reserve all artifact paths used by the MVP pipeline."""

    return RunArtifactManifest(
        run_id=scaffold.run_id,
        artifacts={
            "run_metadata": ArtifactRef(
                path=Path("run_metadata.json"),
                owner="Member 1",
                description="Stable metadata for this pipeline run.",
                status=ArtifactStatus.CREATED,
            ),
            "artifact_manifest": ArtifactRef(
                path=Path("artifact_manifest.json"),
                owner="Member 1",
                description="Registry of expected run artifact paths.",
                status=ArtifactStatus.CREATED,
            ),
            "manifest_snapshot": ArtifactRef(
                path=Path("inputs/manifest_snapshot.yaml"),
                owner="Member 1",
                description="Copy of the Hiring Bundle manifest used for this run.",
            ),
            "context_packet": ArtifactRef(
                path=Path("inputs/context_packet.json"),
                owner="Member 1",
                description="Validated context packet produced by the Intake Agent.",
            ),
            "intake_findings": ArtifactRef(
                path=Path("artifacts/intake_findings.json"),
                owner="Member 1",
                description="Validation warnings and intake-stage findings.",
            ),
            "candidate_profile": ArtifactRef(
                path=Path("artifacts/candidate_profile.json"),
                owner="Member 2",
                description="Extracted candidate profile with confidence and evidence.",
            ),
            "candidate_profiles": ArtifactRef(
                path=Path("artifacts/candidate_profiles.json"),
                owner="Member 2",
                description="All extracted candidate profiles for multi-candidate runs.",
            ),
            "match_scores": ArtifactRef(
                path=Path("artifacts/match_scores.json"),
                owner="Member 2",
                description="JD fit scores and must-have/nice-to-have checks.",
            ),
            "compliance_flags": ArtifactRef(
                path=Path("artifacts/compliance_flags.md"),
                owner="Member 3",
                description="Human-readable EEO and compliance flags.",
            ),
            "verification_findings": ArtifactRef(
                path=Path("artifacts/verification_findings.json"),
                owner="Member 3",
                description="Credential and provided-profile consistency findings.",
            ),
            "anomaly_findings": ArtifactRef(
                path=Path("artifacts/anomaly_findings.json"),
                owner="Member 3",
                description="Duplicate, multi-role, contradiction, or surge findings.",
            ),
            "final_decision": ArtifactRef(
                path=Path("artifacts/final_decision.json"),
                owner="Member 1 + Member 3",
                description="Final routing recommendations requiring human review.",
            ),
            "shortlist": ArtifactRef(
                path=Path("artifacts/shortlist.csv"),
                owner="Member 1 + Member 3",
                description="Ranked candidate shortlist for demo review.",
            ),
            "hiring_packet": ArtifactRef(
                path=Path("artifacts/hiring_packet.json"),
                owner="Member 1 + Member 3",
                description="Simplified mock HRIS-ready hiring packet.",
            ),
            "interview_schedule": ArtifactRef(
                path=Path("artifacts/interview_schedule.json"),
                owner="Member 2",
                description=(
                    "Optional v2 mock interview schedule suggestions requiring "
                    "human confirmation."
                ),
                required_for_mvp=False,
            ),
            "fraud_findings": ArtifactRef(
                path=Path("artifacts/fraud_findings.json"),
                owner="Member 3",
                description="Optional v2 fraud-specific risk findings for human review.",
                required_for_mvp=False,
            ),
            "ats_payload": ArtifactRef(
                path=Path("artifacts/ats_payload.json"),
                owner="Member 3",
                description=(
                    "Optional v2 mock ATS-ready output payload. No real ATS API "
                    "is called."
                ),
                required_for_mvp=False,
            ),
            "audit_log": ArtifactRef(
                path=Path("artifacts/audit_log.md"),
                owner="Member 1",
                description="Human-readable processing trace and decisions.",
                status=ArtifactStatus.CREATED,
            ),
            "metrics": ArtifactRef(
                path=Path("artifacts/metrics.json"),
                owner="Member 1 + Member 3",
                description="Run metrics, throughput, exception rates, and routing counts.",
                status=ArtifactStatus.CREATED,
            ),
            "audit_events": ArtifactRef(
                path=Path("logs/audit_events.jsonl"),
                owner="Member 1",
                description="Append-friendly structured audit event log.",
                status=ArtifactStatus.CREATED,
            ),
        },
    )


def build_initial_audit_log(scaffold: RunScaffold) -> str:
    """Create the starter audit log for a newly scaffolded run."""

    return (
        "# ICSHPS Audit Log\n\n"
        f"Run ID: `{scaffold.run_id}`\n\n"
        "Status: `created`\n\n"
        "## Created in Sprint 1\n\n"
        "- Run folder scaffold created.\n"
        "- Artifact paths reserved.\n"
        "- Metrics file initialized.\n"
        "- Audit event log initialized.\n\n"
        "## Pending next steps\n\n"
        "- Task 5: Bundle Loader writes `inputs/manifest_snapshot.yaml` and validates files.\n"
        "- Task 6: Intake Agent writes `inputs/context_packet.json` and `artifacts/intake_findings.json`.\n"
        "- Member 2 writes `candidate_profile.json`, `candidate_profiles.json`, and `match_scores.json`.\n"
        "- Member 3 writes compliance, verification, and anomaly findings.\n"
    )


def build_initial_metrics(scaffold: RunScaffold) -> dict[str, Any]:
    """Create deterministic starter metrics for a newly scaffolded run."""

    return {
        "run_id": scaffold.run_id,
        "status": "created",
        "candidate_count": 0,
        **V2_METRIC_DEFAULTS,
        "artifacts_created": [
            "run_metadata.json",
            "artifact_manifest.json",
            "artifacts/audit_log.md",
            "artifacts/metrics.json",
            "logs/audit_events.jsonl",
        ],
        "notes": [
            "Sprint 1 run scaffold initialized.",
            "Downstream metrics will be updated after intake, extraction, matching, and triage.",
        ],
    }


def _create_directories(scaffold: RunScaffold) -> None:
    """Create the required run subdirectories."""

    scaffold.inputs_dir.mkdir(parents=True, exist_ok=True)
    scaffold.artifacts_dir.mkdir(parents=True, exist_ok=True)
    scaffold.logs_dir.mkdir(parents=True, exist_ok=True)
    scaffold.tmp_dir.mkdir(parents=True, exist_ok=True)


def _safe_reset_run_dir(run_dir: Path, runs_root: Path) -> None:
    """Remove an existing run directory only if it is safely inside runs_root."""

    runs_root.mkdir(parents=True, exist_ok=True)

    resolved_run_dir = run_dir.resolve()
    resolved_runs_root = runs_root.resolve()

    if not resolved_run_dir.is_relative_to(resolved_runs_root):
        raise ValueError(
            f"Refusing to reset run directory outside runs root: {resolved_run_dir}"
        )

    if run_dir.exists():
        shutil.rmtree(run_dir)
