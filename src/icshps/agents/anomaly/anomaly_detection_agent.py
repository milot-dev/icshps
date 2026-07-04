from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from icshps.schemas import (
    CandidateProfile,
    EmploymentRecord,
    EvidenceRef,
    FindingCategory,
    Severity,
    Finding,
    FindingsArtifact,
)
from icshps.utils.dates import date_ranges_overlap
from icshps.utils.file_io import read_json_object, read_yaml_object

AGENT_NAME = "surge_mode_detection_v1"
ANOMALY_AGENT_NAME = "anomaly_detection_agent_v1"
FRAUD_AGENT_NAME = "fraud_anomaly_agent_v1"


def build_anomaly_findings(
    *,
    run_id: str,
    candidate_profiles: list[CandidateProfile],
    application_history_path: Path | None = None,
    application_volume_path: Path | None = None,
) -> FindingsArtifact:
    """Detect duplicate, multi-role, employment-overlap, and surge anomalies."""

    findings: list[Finding] = []
    findings.extend(_duplicate_candidate_findings(candidate_profiles))
    findings.extend(
        _employment_overlap_findings(
            candidate_profiles=candidate_profiles,
            starting_index=len(findings) + 1,
        )
    )
    findings.extend(
        _multi_role_findings(
            application_history_path=application_history_path,
            starting_index=len(findings) + 1,
        )
    )
    findings.extend(
        build_surge_mode_findings(
            run_id=run_id,
            application_volume_path=application_volume_path,
        ).findings
    )

    return FindingsArtifact(run_id=run_id, findings=findings)


def build_fraud_findings(
    *,
    run_id: str,
    candidate_profiles: list[CandidateProfile],
    fraud_signals_path: Path | None = None,
) -> FindingsArtifact:
    """Detect local mock fraud signals and identity-collision risk."""

    findings: list[Finding] = []
    findings.extend(_identity_collision_findings(candidate_profiles))
    findings.extend(
        _mock_fraud_signal_findings(
            fraud_signals_path=fraud_signals_path,
            starting_index=len(findings) + 1,
        )
    )
    return FindingsArtifact(run_id=run_id, findings=findings)


def build_surge_mode_findings(
    *,
    run_id: str,
    application_volume_path: Path | None = None,
) -> FindingsArtifact:
    """Detect high-volume or surge application scenarios based on bundle metadata."""

    findings: list[Finding] = []

    if application_volume_path is None or not application_volume_path.exists():
        return FindingsArtifact(run_id=run_id, findings=findings)

    volume_data = _load_application_volume_metadata(application_volume_path)
    if not volume_data:
        return FindingsArtifact(run_id=run_id, findings=findings)

    surge_conditions = _check_surge_conditions(volume_data)

    if surge_conditions["is_surge"]:
        findings.append(
            Finding(
                id="surge-mode-001",
                source_agent=AGENT_NAME,
                category=FindingCategory.ANOMALY,
                severity=Severity.INFO,
                title="Surge processing mode activated",
                description=_build_surge_description(surge_conditions, volume_data),
                reason=(
                    "Bulk application volume detected. "
                    "Processing mode adjusted for high-volume scenarios."
                ),
                confidence=1.0,
                evidence=[
                    EvidenceRef(
                        source_path=application_volume_path,
                        source_type="application_volume_metadata",
                        section="surge_indicators",
                        text_snippet=_build_evidence_snippet(
                            surge_conditions, volume_data
                        ),
                        confidence=1.0,
                    )
                ],
                recommendation=(
                    "Candidates are being processed in surge mode. "
                    "Fast-track candidates with strong matches; "
                    "prioritize high-confidence recommendations."
                ),
                requires_human_review=False,
            )
        )

    return FindingsArtifact(run_id=run_id, findings=findings)


def _load_application_volume_metadata(path: Path) -> dict[str, Any]:
    """Load application volume metadata from YAML or JSON file."""

    if not path.exists() or path.stat().st_size == 0:
        return {}

    try:
        if path.suffix.lower() in (".yaml", ".yml"):
            return read_yaml_object(path)
        elif path.suffix.lower() == ".json":
            return read_json_object(path)
    except (ValueError, yaml.YAMLError):
        return {}

    return {}


def _load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return read_json_object(path)
    return read_yaml_object(path)


def _identity_collision_findings(
    candidate_profiles: list[CandidateProfile],
) -> list[Finding]:
    findings: list[Finding] = []

    for field_name, getter in (
        ("email", lambda profile: profile.email.value if profile.email else None),
        ("phone", lambda profile: profile.phone.value if profile.phone else None),
    ):
        profiles_by_value: dict[str, list[CandidateProfile]] = {}
        for profile in candidate_profiles:
            value = getter(profile)
            if value:
                profiles_by_value.setdefault(value.strip().lower(), []).append(profile)

        for _, profiles in sorted(profiles_by_value.items()):
            candidate_ids = {profile.candidate_id for profile in profiles}
            if len(candidate_ids) < 2:
                continue

            first = sorted(
                profiles,
                key=lambda item: (item.candidate_id, item.application_id),
            )[0]
            findings.append(
                Finding(
                    id=f"fraud-identity-collision-{field_name}-{len(findings) + 1:03d}",
                    source_agent=FRAUD_AGENT_NAME,
                    category=FindingCategory.FRAUD,
                    severity=Severity.WARNING,
                    title="Possible candidate identity collision",
                    description=(
                        f"Multiple candidate IDs share the same {field_name} value."
                    ),
                    reason=(
                        "Shared contact details across candidate IDs can indicate "
                        "duplicate, proxy, or synthetic application risk."
                    ),
                    candidate_id=first.candidate_id,
                    application_id=first.application_id,
                    confidence=0.85,
                    evidence=[
                        ref for profile in profiles for ref in profile.evidence_index
                    ],
                    recommendation="Route to manual fraud review before downstream action.",
                    requires_human_review=True,
                )
            )

    return findings


def _mock_fraud_signal_findings(
    *,
    fraud_signals_path: Path | None,
    starting_index: int,
) -> list[Finding]:
    if (
        fraud_signals_path is None
        or not fraud_signals_path.exists()
        or fraud_signals_path.stat().st_size == 0
    ):
        return []

    payload = _load_mapping(fraud_signals_path)
    raw_signals = payload.get("fraud_signals") or payload.get("signals") or []
    if not isinstance(raw_signals, list):
        return []

    findings: list[Finding] = []
    for item in raw_signals:
        if not isinstance(item, dict):
            continue

        signal_type = str(
            item.get("type") or item.get("signal") or "mock_fraud_signal"
        ).strip()
        description = str(
            item.get("description")
            or item.get("reason")
            or "Mock fraud signal requires human review."
        )
        severity = Severity(str(item.get("severity", Severity.WARNING.value)))
        confidence = max(0.0, min(float(item.get("confidence", 0.8) or 0.0), 1.0))

        findings.append(
            Finding(
                id=f"fraud-mock-signal-{starting_index + len(findings):03d}",
                source_agent=FRAUD_AGENT_NAME,
                category=FindingCategory.FRAUD,
                severity=severity,
                title=str(item.get("title") or _title_from_signal_type(signal_type)),
                description=description,
                reason=description,
                candidate_id=_optional_string(item.get("candidate_id")),
                application_id=_optional_string(item.get("application_id")),
                confidence=confidence,
                evidence=[
                    EvidenceRef(
                        source_path=fraud_signals_path,
                        source_type="mock_fraud_signals",
                        section=signal_type,
                        text_snippet=description,
                        confidence=confidence,
                    )
                ],
                recommendation="Route to manual fraud review before downstream action.",
                requires_human_review=True,
            )
        )

    return findings


def _duplicate_candidate_findings(
    candidate_profiles: list[CandidateProfile],
) -> list[Finding]:
    profiles_by_email: dict[str, list[CandidateProfile]] = {}
    for profile in candidate_profiles:
        email = profile.email.value if profile.email else None
        if email:
            profiles_by_email.setdefault(email.strip().lower(), []).append(profile)

    findings: list[Finding] = []
    for email, profiles in sorted(profiles_by_email.items()):
        if len(profiles) < 2:
            continue
        findings.append(
            Finding(
                id=f"anomaly-duplicate-candidate-{len(findings) + 1:03d}",
                source_agent=ANOMALY_AGENT_NAME,
                category=FindingCategory.ANOMALY,
                severity=Severity.WARNING,
                title="Duplicate candidate applications detected",
                description=f"Multiple applications share candidate email '{email}'.",
                reason="Duplicate applications should be grouped for reviewer handling.",
                candidate_id=profiles[0].candidate_id,
                application_id=profiles[0].application_id,
                confidence=1.0,
                evidence=[
                    ref for profile in profiles for ref in profile.evidence_index
                ],
                recommendation="Route to duplicate / multi-role review.",
                requires_human_review=True,
            )
        )

    return findings


def _employment_overlap_findings(
    *,
    candidate_profiles: list[CandidateProfile],
    starting_index: int,
) -> list[Finding]:
    findings: list[Finding] = []

    for profile in candidate_profiles:
        for left_index, left in enumerate(profile.employment_history):
            for right in profile.employment_history[left_index + 1 :]:
                if not _employment_ranges_overlap(left, right):
                    continue
                findings.append(
                    Finding(
                        id=f"anomaly-employment-overlap-{starting_index + len(findings):03d}",
                        source_agent=ANOMALY_AGENT_NAME,
                        category=FindingCategory.ANOMALY,
                        severity=Severity.WARNING,
                        title="Overlapping employment history detected",
                        description=(
                            f"Roles at '{left.company}' and '{right.company}' "
                            "have overlapping dates."
                        ),
                        reason="Implausible overlapping resume roles require manual review.",
                        candidate_id=profile.candidate_id,
                        application_id=profile.application_id,
                        confidence=1.0,
                        evidence=[*left.evidence, *right.evidence],
                        recommendation="Route to employment history inconsistency manual review.",
                        requires_human_review=True,
                    )
                )

    return findings


def _multi_role_findings(
    *,
    application_history_path: Path | None,
    starting_index: int,
) -> list[Finding]:
    if (
        application_history_path is None
        or not application_history_path.exists()
        or application_history_path.stat().st_size == 0
    ):
        return []

    try:
        payload = read_yaml_object(application_history_path)
    except yaml.YAMLError:
        return []

    candidate_id = str(payload.get("candidate_id", "")).strip()
    applications = [
        item for item in payload.get("applications", []) if isinstance(item, dict)
    ]
    roles = {
        str(item.get("role_id") or item.get("job_id") or "").strip()
        for item in applications
    }
    roles.discard("")

    if not candidate_id or len(roles) < 2:
        return []

    return [
        Finding(
            id=f"anomaly-multi-role-{starting_index:03d}",
            source_agent=ANOMALY_AGENT_NAME,
            category=FindingCategory.ANOMALY,
            severity=Severity.WARNING,
            title="Candidate applied to multiple roles",
            description=f"Candidate '{candidate_id}' appears across {len(roles)} roles.",
            reason="Same-candidate multi-role activity should be linked for review.",
            candidate_id=candidate_id,
            confidence=1.0,
            evidence=[
                EvidenceRef(
                    source_path=application_history_path,
                    source_type="mock_application_history",
                    section="applications",
                    text_snippet=", ".join(sorted(roles)),
                    confidence=1.0,
                )
            ],
            recommendation="Route to duplicate / multi-role review.",
            requires_human_review=True,
        )
    ]


def _employment_ranges_overlap(left: EmploymentRecord, right: EmploymentRecord) -> bool:
    return date_ranges_overlap(
        left.start_date,
        left.end_date,
        right.start_date,
        right.end_date,
    )


def _check_surge_conditions(volume_data: dict[str, Any]) -> dict[str, bool | int]:
    """Determine if surge processing mode should be activated."""

    is_surge = False
    triggered_by: list[str] = []

    bulk_flag = volume_data.get("bulk_application_flag", False)
    if bulk_flag:
        is_surge = True
        triggered_by.append("bulk_application_flag")

    application_count = volume_data.get("application_count", 0)
    threshold = volume_data.get("surge_threshold", 50)
    if application_count >= threshold:
        is_surge = True
        triggered_by.append(f"application_count ({application_count} >= {threshold})")

    viral_indicator = volume_data.get("viral_job_post", False)
    if viral_indicator:
        is_surge = True
        triggered_by.append("viral_job_post_indicator")

    return {
        "is_surge": is_surge,
        "triggered_by": triggered_by,
        "application_count": application_count,
        "threshold": threshold,
    }


def _build_surge_description(
    surge_conditions: dict[str, bool | int | list[str]],
    volume_data: dict[str, Any],
) -> str:
    """Build a human-readable description of surge conditions."""

    if not surge_conditions.get("is_surge"):
        return "No surge conditions detected."

    triggered = surge_conditions.get("triggered_by", [])
    app_count = surge_conditions.get("application_count", 0)

    parts = ["Surge processing mode activated due to:"]
    for trigger in triggered:
        parts.append(f"  - {trigger}")

    if app_count > 0:
        parts.append(f"Total applications in this batch: {app_count}")

    return " ".join(parts)


def _build_evidence_snippet(
    surge_conditions: dict[str, bool | int | list[str]],
    volume_data: dict[str, Any],
) -> str:
    """Build an evidence snippet showing which surge indicators were triggered."""

    triggered = surge_conditions.get("triggered_by", [])
    if not triggered:
        return "No surge indicators detected."

    snippet_parts = ["Surge indicators detected:"]
    for trigger in triggered:
        snippet_parts.append(f"  • {trigger}")

    if volume_data.get("application_count"):
        snippet_parts.append(
            f"  • application_count: {volume_data.get('application_count')}"
        )

    return "; ".join(snippet_parts)


def _title_from_signal_type(signal_type: str) -> str:
    return signal_type.replace("_", " ").replace("-", " ").strip().title()


def _optional_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
