from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from icshps.schemas import (
    CertificationRecord,
    EvidenceRef,
    EducationRecord,
    FindingCategory,
    Severity,
    Finding,
    FindingsArtifact,
    CandidateProfile,
)

AGENT_NAME = "mandatory_certification_check_v1"
CREDENTIAL_AGENT_NAME = "credential_verification_agent_v1"


def build_credential_verification_findings(
    *,
    run_id: str,
    candidate_profile: CandidateProfile,
    credential_evidence_path: Path | None = None,
) -> FindingsArtifact:
    """Check education and certifications against local mock credential evidence."""

    mock_evidence = _load_yaml_object(credential_evidence_path)
    findings: list[Finding] = []

    for education in candidate_profile.education:
        finding = _build_education_verification_finding(
            candidate_profile=candidate_profile,
            education=education,
            credential_evidence_path=credential_evidence_path,
            mock_evidence=mock_evidence,
            index=len(findings) + 1,
        )
        if finding is not None:
            findings.append(finding)

    for certification in candidate_profile.certifications:
        finding = _build_certification_verification_finding(
            candidate_profile=candidate_profile,
            certification=certification,
            credential_evidence_path=credential_evidence_path,
            mock_evidence=mock_evidence,
            index=len(findings) + 1,
        )
        if finding is not None:
            findings.append(finding)

    bundle_signal = _bundle_level_credential_signal(
        candidate_profile=candidate_profile,
        credential_evidence_path=credential_evidence_path,
        mock_evidence=mock_evidence,
        index=len(findings) + 1,
    )
    if bundle_signal is not None:
        findings.append(bundle_signal)

    return FindingsArtifact(run_id=run_id, findings=findings)


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


def _build_education_verification_finding(
    *,
    candidate_profile: CandidateProfile,
    education: EducationRecord,
    credential_evidence_path: Path | None,
    mock_evidence: dict[str, Any],
    index: int,
) -> Finding | None:
    record = _matching_mock_record(
        mock_evidence.get("education_registry"),
        fields={"institution": education.institution, "degree": education.degree},
    )
    status = _verification_status(record, education.verification_status)

    if education.is_international and status in {"missing", "pending", "unverified"}:
        return _credential_finding(
            finding_id=f"credential-education-pending-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="International degree pending verification",
            description=(
                f"Education from '{education.institution}' needs bundle-provided "
                "mock registry verification."
            ),
            reason="International degrees are routed to pending credential verification.",
            evidence=_credential_evidence(
                source_evidence=education.evidence,
                credential_evidence_path=credential_evidence_path,
                section="education",
                snippet=education.institution,
            ),
            recommendation="Route to pending credential verification.",
        )

    if status == "verified":
        return _credential_finding(
            finding_id=f"credential-education-verified-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.INFO,
            title="Education credential verified",
            description=f"Education at '{education.institution}' matched mock evidence.",
            reason="The Hiring Bundle mock registry marks this education record verified.",
            evidence=_credential_evidence(
                source_evidence=education.evidence,
                credential_evidence_path=credential_evidence_path,
                section="education",
                snippet=education.institution,
            ),
            recommendation="No credential exception for this education record.",
            requires_human_review=False,
        )

    if status in {"missing", "pending", "unverified"}:
        return _credential_finding(
            finding_id=f"credential-education-review-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="Education credential needs verification",
            description=f"Education at '{education.institution}' was not verified.",
            reason="The Hiring Bundle mock registry does not verify this education record.",
            evidence=_credential_evidence(
                source_evidence=education.evidence,
                credential_evidence_path=credential_evidence_path,
                section="education",
                snippet=education.institution,
            ),
            recommendation="Route to pending credential verification.",
        )

    return None


def _build_certification_verification_finding(
    *,
    candidate_profile: CandidateProfile,
    certification: CertificationRecord,
    credential_evidence_path: Path | None,
    mock_evidence: dict[str, Any],
    index: int,
) -> Finding | None:
    status = _verification_status(
        _matching_mock_record(
            mock_evidence.get("certification_registry"),
            fields={"name": certification.name, "issuer": certification.issuer},
        ),
        certification.verification_status,
    )

    if certification.confidence < 0.60 or "low_confidence" in status:
        return _credential_finding(
            finding_id=f"credential-certification-manual-review-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="Certification requires manual review",
            description=f"Certification '{certification.name}' has low-confidence evidence.",
            reason="Low-confidence or handwritten certification evidence requires human review.",
            evidence=_credential_evidence(
                source_evidence=certification.evidence,
                credential_evidence_path=credential_evidence_path,
                section="certifications",
                snippet=certification.name,
            ),
            recommendation="Route to manual credential review.",
        )

    if status == "verified":
        return _credential_finding(
            finding_id=f"credential-certification-verified-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.INFO,
            title="Certification verified",
            description=f"Certification '{certification.name}' matched mock authority data.",
            reason="The Hiring Bundle mock certification authority marks this record verified.",
            evidence=_credential_evidence(
                source_evidence=certification.evidence,
                credential_evidence_path=credential_evidence_path,
                section="certifications",
                snippet=certification.name,
            ),
            recommendation="No credential exception for this certification.",
            requires_human_review=False,
        )

    if status == "revoked":
        return _credential_finding(
            finding_id=f"credential-certification-revoked-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.BLOCKING,
            title="Certification marked revoked",
            description=f"Certification '{certification.name}' is revoked in mock evidence.",
            reason="Revoked credential evidence blocks automatic advancement pending human approval.",
            evidence=_credential_evidence(
                source_evidence=certification.evidence,
                credential_evidence_path=credential_evidence_path,
                section="certifications",
                snippet=certification.name,
            ),
            recommendation="Route as recommended rejection pending human approval.",
        )

    if status in {"missing", "pending", "unverified"}:
        return _credential_finding(
            finding_id=f"credential-certification-review-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="Certification needs verification",
            description=f"Certification '{certification.name}' was not verified.",
            reason="The Hiring Bundle mock certification authority does not verify this record.",
            evidence=_credential_evidence(
                source_evidence=certification.evidence,
                credential_evidence_path=credential_evidence_path,
                section="certifications",
                snippet=certification.name,
            ),
            recommendation="Route to pending credential verification.",
        )

    return None


def _bundle_level_credential_signal(
    *,
    candidate_profile: CandidateProfile,
    credential_evidence_path: Path | None,
    mock_evidence: dict[str, Any],
    index: int,
) -> Finding | None:
    payload = mock_evidence.get("credential_evidence")
    if not isinstance(payload, dict):
        return None

    status = str(payload.get("status", "")).lower()
    confidence = float(payload.get("confidence", 1.0) or 0.0)
    if "low_confidence" not in status and confidence >= 0.60:
        return None

    return _credential_finding(
        finding_id=f"credential-bundle-manual-review-{index:03d}",
        candidate_profile=candidate_profile,
        severity=Severity.WARNING,
        title="Mock credential evidence requires manual review",
        description="Bundle-provided credential evidence is low confidence.",
        reason="Low-confidence mock evidence cannot be auto-verified.",
        evidence=_credential_evidence(
            source_evidence=[],
            credential_evidence_path=credential_evidence_path,
            section="credential_evidence",
            snippet=str(payload.get("type", "credential evidence")),
        ),
        recommendation="Route to manual credential review.",
    )


def _credential_finding(
    *,
    finding_id: str,
    candidate_profile: CandidateProfile,
    severity: Severity,
    title: str,
    description: str,
    reason: str,
    evidence: list[EvidenceRef],
    recommendation: str,
    requires_human_review: bool = True,
) -> Finding:
    return Finding(
        id=finding_id,
        source_agent=CREDENTIAL_AGENT_NAME,
        category=FindingCategory.CREDENTIAL,
        severity=severity,
        title=title,
        description=description,
        reason=reason,
        candidate_id=candidate_profile.candidate_id,
        application_id=candidate_profile.application_id,
        confidence=1.0,
        evidence=evidence,
        recommendation=recommendation,
        requires_human_review=requires_human_review,
    )


def _load_yaml_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return {}

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _matching_mock_record(
    records: Any,
    *,
    fields: dict[str, str | None],
) -> dict[str, Any] | None:
    if not isinstance(records, list):
        return None

    wanted = {
        key: _normalize(value)
        for key, value in fields.items()
        if value is not None and _normalize(value)
    }
    if not wanted:
        return None

    for record in records:
        if not isinstance(record, dict):
            continue
        if all(_normalize(str(record.get(key, ""))) == value for key, value in wanted.items()):
            return record

    return None


def _verification_status(record: dict[str, Any] | None, fallback: str | None) -> str:
    if record is not None:
        return str(record.get("status", "verified")).lower()
    if fallback:
        return fallback.lower()
    return "missing"


def _credential_evidence(
    *,
    source_evidence: list[EvidenceRef],
    credential_evidence_path: Path | None,
    section: str,
    snippet: str,
) -> list[EvidenceRef]:
    evidence = list(source_evidence)
    if credential_evidence_path is not None:
        evidence.append(
            EvidenceRef(
                source_path=credential_evidence_path,
                source_type="mock_credential_evidence",
                section=section,
                text_snippet=snippet,
                confidence=1.0,
            )
        )
    return evidence


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
