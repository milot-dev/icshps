from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from icshps.schemas import (
    EvidenceRef,
    FindingCategory,
    Severity,
    Finding,
    FindingsArtifact,
    CandidateProfile,
)

AGENT_NAME = "mandatory_certification_check_v1"


def build_mandatory_certification_findings(
    *,
    run_id: str,
    candidate_profile: CandidateProfile,
    skills_matrix_path: Path,
) -> FindingsArtifact:
    """Compare required certifications from the skills matrix with a candidate profile."""

    required = _load_required_certifications(skills_matrix_path)
    candidate_certs = {
        _normalize(cert.name): cert for cert in candidate_profile.certifications
    }
    findings: list[Finding] = []

    for index, required_cert in enumerate(required, start=1):
        normalized_required = _normalize(required_cert["name"])
        matched = normalized_required in candidate_certs
        severity = (
            Severity.INFO if matched else Severity(str(required_cert["severity"]))
        )
        title = (
            "Mandatory certification present"
            if matched
            else "Mandatory certification missing"
        )
        reason = (
            f"Candidate profile includes required certification '{required_cert['name']}'."
            if matched
            else f"Candidate profile does not include required certification '{required_cert['name']}'."
        )

        findings.append(
            Finding(
                id=f"certification-required-{index:03d}",
                source_agent=AGENT_NAME,
                category=FindingCategory.MATCHING,
                severity=severity,
                title=title,
                description=reason,
                reason=reason,
                candidate_id=candidate_profile.candidate_id,
                application_id=candidate_profile.application_id,
                confidence=1.0,
                evidence=[
                    EvidenceRef(
                        source_path=skills_matrix_path,
                        source_type="skills_matrix",
                        section="mandatory_certifications",
                        text_snippet=required_cert["name"],
                        confidence=1.0,
                    )
                ],
                recommendation=(
                    "No action needed for this certification."
                    if matched
                    else "Route as recommended rejection pending human approval."
                ),
                requires_human_review=not matched,
            )
        )

    return FindingsArtifact(run_id=run_id, findings=findings)


def _load_required_certifications(skills_matrix_path: Path) -> list[dict[str, str]]:
    if not skills_matrix_path.exists() or skills_matrix_path.stat().st_size == 0:
        return []

    payload = yaml.safe_load(skills_matrix_path.read_text(encoding="utf-8")) or {}
    raw_items = (
        payload.get("mandatory_certifications")
        or payload.get("required_certifications")
        or payload.get("certifications")
        or []
    )

    required: list[dict[str, str]] = []
    for item in raw_items:
        parsed = _parse_required_certification(item)
        if parsed is not None:
            required.append(parsed)

    return required


def _parse_required_certification(item: Any) -> dict[str, str] | None:
    if isinstance(item, str):
        name = item.strip()
        severity = Severity.BLOCKING.value
    elif isinstance(item, dict):
        name = str(item.get("name", "")).strip()
        severity = str(item.get("missing_severity", Severity.BLOCKING.value))
    else:
        return None

    if not name:
        return None

    Severity(severity)
    return {"name": name, "severity": severity}


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").split())
