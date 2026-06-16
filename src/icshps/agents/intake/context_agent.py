from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from icshps.schemas import (
    FindingCategory,
    Severity,
    BundleContext,
    Finding,
    FindingsArtifact,
    ArtifactStatus,
    RunArtifactManifest,
)
from icshps.services import LoadedBundle, RunScaffold, snapshot_manifest_to_run

AGENT_NAME = "application_intake_context_agent"
CONTEXT_PACKET_FILENAME = "context_packet.json"
INTAKE_FINDINGS_FILENAME = "intake_findings.json"


@dataclass(frozen=True)
class ApplicationIntakeResult:
    """Controlled result returned after Application Intake & Context Agent writes its run artifacts."""

    run_id: str
    ready_for_downstream: bool
    context_packet_path: Path | None
    intake_findings_path: Path
    finding_count: int
    blocking_finding_count: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.ready_for_downstream and self.blocking_finding_count == 0


def run_application_intake(
    *,
    loaded_bundle: LoadedBundle,
    scaffold: RunScaffold,
) -> ApplicationIntakeResult:
    """
    Build Application Intake & Context Agent artifacts from an already validated LoadedBundle.

    Application intentionally does not re-read manifest.yaml. Task 5 owns manifest
    parsing, path resolution, and file-existence validation. This function only
    consumes the validated loader result and writes run-local artifacts for
    downstream agents.
    """

    _ensure_context_matches_run(loaded_bundle.context, scaffold)

    manifest_snapshot_path = _snapshot_manifest_if_available(
        loaded_bundle=loaded_bundle,
        scaffold=scaffold,
    )

    context_packet_path = None
    if loaded_bundle.context is not None:
        context_packet_path = scaffold.inputs_dir / CONTEXT_PACKET_FILENAME
        _write_json(context_packet_path, loaded_bundle.context)

    findings_artifact = build_intake_findings(loaded_bundle)
    intake_findings_path = scaffold.artifacts_dir / INTAKE_FINDINGS_FILENAME
    _write_json(intake_findings_path, findings_artifact)

    ready_for_downstream = bool(
        loaded_bundle.ok
        and loaded_bundle.context is not None
        and loaded_bundle.context.is_ready
        and not _has_blocking_findings(findings_artifact)
    )

    _append_audit_event(
        scaffold.logs_dir / "audit_events.jsonl",
        {
            "event": "application_intake_completed",
            "run_id": scaffold.run_id,
            "agent": AGENT_NAME,
            "status": "ready" if ready_for_downstream else "blocked",
            "ready_for_downstream": ready_for_downstream,
            "context_packet_written": context_packet_path is not None,
            "intake_findings_written": True,
            "finding_count": len(findings_artifact.findings),
            "blocking_finding_count": _blocking_finding_count(findings_artifact),
        },
    )

    _append_audit_log_section(
        scaffold=scaffold,
        loaded_bundle=loaded_bundle,
        context_packet_path=context_packet_path,
        intake_findings_path=intake_findings_path,
        manifest_snapshot_path=manifest_snapshot_path,
        ready_for_downstream=ready_for_downstream,
        finding_count=len(findings_artifact.findings),
    )

    _update_metrics(
        scaffold=scaffold,
        loaded_bundle=loaded_bundle,
        ready_for_downstream=ready_for_downstream,
        finding_count=len(findings_artifact.findings),
        blocking_finding_count=_blocking_finding_count(findings_artifact),
    )

    _mark_artifacts_created(
        scaffold=scaffold,
        artifact_keys=_created_artifact_keys(
            manifest_snapshot_path=manifest_snapshot_path,
            context_packet_path=context_packet_path,
        ),
    )

    return ApplicationIntakeResult(
        run_id=scaffold.run_id,
        ready_for_downstream=ready_for_downstream,
        context_packet_path=context_packet_path,
        intake_findings_path=intake_findings_path,
        finding_count=len(findings_artifact.findings),
        blocking_finding_count=_blocking_finding_count(findings_artifact),
        warnings=loaded_bundle.warnings,
        errors=loaded_bundle.errors,
    )


def build_intake_findings(loaded_bundle: LoadedBundle) -> FindingsArtifact:
    """Create deterministic, audit-friendly findings from loader and intake checks."""

    run_id = loaded_bundle.context.run_id if loaded_bundle.context else "unknown_run"
    findings: list[Finding] = []

    if loaded_bundle.context is not None:
        findings.append(_ready_signal(loaded_bundle.context))
        findings.extend(_candidate_job_consistency_findings(loaded_bundle.context))
        findings.extend(_scenario_optional_input_findings(loaded_bundle.context))

    for index, warning in enumerate(loaded_bundle.warnings, start=1):
        findings.append(
            Finding(
                id=f"intake-loader-warning-{index:03d}",
                source_agent=AGENT_NAME,
                category=FindingCategory.INTAKE,
                severity=Severity.WARNING,
                title="Bundle loader warning",
                description=warning,
                confidence=1.0,
                evidence=[],
                recommendation="Review the optional input before relying on scenario-specific checks.",
                requires_human_review=True,
            )
        )

    for index, error in enumerate(loaded_bundle.errors, start=1):
        findings.append(
            Finding(
                id=f"intake-loader-error-{index:03d}",
                source_agent=AGENT_NAME,
                category=FindingCategory.INTAKE,
                severity=Severity.BLOCKING,
                title="Bundle validation error",
                description=error,
                confidence=1.0,
                evidence=[],
                recommendation="Fix the Hiring Bundle before running downstream agents.",
                requires_human_review=True,
            )
        )

    return FindingsArtifact(run_id=run_id, findings=findings)


def _ready_signal(context: BundleContext) -> Finding:
    status_text = "ready" if context.is_ready else "not ready"

    return Finding(
        id="intake-context-summary-001",
        source_agent=AGENT_NAME,
        category=FindingCategory.INTAKE,
        severity=Severity.INFO if context.is_ready else Severity.WARNING,
        title="Application context prepared",
        description=(
            f"Bundle '{context.bundle.id}' for scenario '{context.scenario.type}' "
            f"was classified and is {status_text} for downstream processing."
        ),
        confidence=1.0,
        evidence=context.evidence_index,
        recommendation=(
            "Proceed to resume extraction."
            if context.is_ready
            else "Resolve validation errors before running extraction."
        ),
        requires_human_review=not context.is_ready,
    )


def _candidate_job_consistency_findings(context: BundleContext) -> list[Finding]:
    findings: list[Finding] = []

    seen_candidate_ids: set[str] = set()
    duplicate_candidate_ids: set[str] = set()

    for candidate in context.candidates:
        if candidate.id in seen_candidate_ids:
            duplicate_candidate_ids.add(candidate.id)

        seen_candidate_ids.add(candidate.id)

        if candidate.target_job_id != context.job.id:
            findings.append(
                Finding(
                    id=f"intake-candidate-job-mismatch-{candidate.application_id}",
                    source_agent=AGENT_NAME,
                    category=FindingCategory.INTAKE,
                    severity=Severity.BLOCKING,
                    title="Candidate target job does not match bundle job",
                    description=(
                        f"Application '{candidate.application_id}' targets job "
                        f"'{candidate.target_job_id}', but this bundle job is '{context.job.id}'."
                    ),
                    candidate_id=candidate.id,
                    application_id=candidate.application_id,
                    confidence=1.0,
                    evidence=[],
                    recommendation="Move the application to the correct Hiring Bundle or fix manifest.yaml.",
                    requires_human_review=True,
                )
            )

    for duplicate_id in sorted(duplicate_candidate_ids):
        findings.append(
            Finding(
                id=f"intake-duplicate-candidate-id-{duplicate_id}",
                source_agent=AGENT_NAME,
                category=FindingCategory.INTAKE,
                severity=Severity.BLOCKING,
                title="Duplicate candidate id in bundle",
                description=f"Candidate id '{duplicate_id}' appears more than once in this bundle.",
                candidate_id=duplicate_id,
                confidence=1.0,
                evidence=[],
                recommendation="Use unique candidate ids so downstream artifacts can be joined safely.",
                requires_human_review=True,
            )
        )

    return findings


def _scenario_optional_input_findings(context: BundleContext) -> list[Finding]:
    """Warn when a scenario appears to need optional mock data that is not declared."""

    scenario_type = context.scenario.type.lower()
    scenario_requirements = {
        "linkedin_profiles": ("linkedin", "employment", "contradict"),
        "application_history": ("duplicate", "multi_role", "multi-role"),
        "credential_evidence": ("credential", "certification", "degree"),
        "application_volume": ("surge", "bulk", "viral"),
    }

    findings: list[Finding] = []

    for field_name, keywords in scenario_requirements.items():
        if not any(keyword in scenario_type for keyword in keywords):
            continue

        optional_path = getattr(context.optional_inputs, field_name)
        if optional_path is not None:
            continue

        findings.append(
            Finding(
                id=f"intake-missing-scenario-input-{field_name}",
                source_agent=AGENT_NAME,
                category=FindingCategory.INTAKE,
                severity=Severity.WARNING,
                title="Scenario-specific optional input not declared",
                description=(
                    f"Scenario '{context.scenario.type}' may need optional input "
                    f"'{field_name}', but manifest.yaml does not declare it."
                ),
                confidence=0.8,
                evidence=[],
                recommendation=(
                    "Add the mock input file before demonstrating this scenario, "
                    "or keep the scenario as a basic Sprint 1 placeholder."
                ),
                requires_human_review=True,
            )
        )

    return findings


def _ensure_context_matches_run(
    context: BundleContext | None, scaffold: RunScaffold
) -> None:
    if context is None:
        return

    if context.run_id != scaffold.run_id:
        raise ValueError(
            "Loaded BundleContext run_id does not match RunScaffold run_id: "
            f"{context.run_id} != {scaffold.run_id}"
        )


def _snapshot_manifest_if_available(
    *,
    loaded_bundle: LoadedBundle,
    scaffold: RunScaffold,
) -> Path | None:
    if not loaded_bundle.manifest_path.exists():
        return None

    return snapshot_manifest_to_run(loaded_bundle.bundle_path, scaffold)


def _created_artifact_keys(
    *,
    manifest_snapshot_path: Path | None,
    context_packet_path: Path | None,
) -> tuple[str, ...]:
    keys = ["intake_findings"]

    if manifest_snapshot_path is not None:
        keys.append("manifest_snapshot")

    if context_packet_path is not None:
        keys.append("context_packet")

    return tuple(keys)


def _has_blocking_findings(artifact: FindingsArtifact) -> bool:
    return _blocking_finding_count(artifact) > 0


def _blocking_finding_count(artifact: FindingsArtifact) -> int:
    return sum(
        1 for finding in artifact.findings if finding.severity == Severity.BLOCKING
    )


def _append_audit_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, sort_keys=True) + "\n")


def _append_audit_log_section(
    *,
    scaffold: RunScaffold,
    loaded_bundle: LoadedBundle,
    context_packet_path: Path | None,
    intake_findings_path: Path,
    manifest_snapshot_path: Path | None,
    ready_for_downstream: bool,
    finding_count: int,
) -> None:
    status = "ready" if ready_for_downstream else "blocked"

    context_line = (
        f"- Context packet: `{context_packet_path.relative_to(scaffold.run_dir)}`\n"
        if context_packet_path is not None
        else "- Context packet: not written because loader did not return a valid context.\n"
    )

    manifest_line = (
        f"- Manifest snapshot: `{manifest_snapshot_path.relative_to(scaffold.run_dir)}`\n"
        if manifest_snapshot_path is not None
        else "- Manifest snapshot: not available.\n"
    )

    bundle_id = loaded_bundle.context.bundle.id if loaded_bundle.context else "unknown"
    scenario_type = (
        loaded_bundle.context.scenario.type if loaded_bundle.context else "unknown"
    )

    section = (
        "\n## Task 6: Application Intake / Context Agent\n\n"
        f"- Agent: `{AGENT_NAME}`\n"
        f"- Bundle: `{bundle_id}`\n"
        f"- Scenario: `{scenario_type}`\n"
        f"- Intake status: `{status}`\n"
        f"- Findings written: `{finding_count}`\n"
        f"- Intake findings: `{intake_findings_path.relative_to(scaffold.run_dir)}`\n"
        f"{context_line}"
        f"{manifest_line}"
        "- Next allowed step: resume extraction only when intake status is `ready`.\n"
    )

    audit_log_path = scaffold.artifacts_dir / "audit_log.md"

    with audit_log_path.open("a", encoding="utf-8") as file:
        file.write(section)


def _update_metrics(
    *,
    scaffold: RunScaffold,
    loaded_bundle: LoadedBundle,
    ready_for_downstream: bool,
    finding_count: int,
    blocking_finding_count: int,
) -> None:
    metrics_path = scaffold.artifacts_dir / "metrics.json"
    metrics = _read_json_object(metrics_path)
    context = loaded_bundle.context

    metrics["status"] = "intake_ready" if ready_for_downstream else "intake_blocked"
    metrics["candidate_count"] = len(context.candidates) if context else 0
    metrics["intake"] = {
        "agent": AGENT_NAME,
        "bundle_id": context.bundle.id if context else None,
        "scenario_type": context.scenario.type if context else None,
        "ready_for_downstream": ready_for_downstream,
        "warning_count": len(loaded_bundle.warnings),
        "error_count": len(loaded_bundle.errors),
        "finding_count": finding_count,
        "blocking_finding_count": blocking_finding_count,
    }

    artifacts_created = set(metrics.get("artifacts_created", []))
    artifacts_created.update(
        {
            "artifacts/intake_findings.json",
            "logs/audit_events.jsonl",
        }
    )

    if context is not None:
        artifacts_created.add("inputs/context_packet.json")

    if loaded_bundle.manifest_path.exists():
        artifacts_created.add("inputs/manifest_snapshot.yaml")

    metrics["artifacts_created"] = sorted(artifacts_created)

    _write_json(metrics_path, metrics)


def _mark_artifacts_created(
    *,
    scaffold: RunScaffold,
    artifact_keys: tuple[str, ...],
) -> None:
    payload = _read_json_object(scaffold.artifact_manifest_path)
    artifact_manifest = RunArtifactManifest.model_validate(payload)

    for key in artifact_keys:
        artifact_ref = artifact_manifest.artifacts.get(key)
        if artifact_ref is not None:
            artifact_ref.status = ArtifactStatus.CREATED

    _write_json(scaffold.artifact_manifest_path, artifact_manifest)


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object at {path}")

    return raw


def _write_json(path: Path, payload: BaseModel | dict[str, Any]) -> None:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
