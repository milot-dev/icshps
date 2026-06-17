from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from icshps.schemas.common import EvidenceRef, FindingCategory, Severity
from icshps.schemas.findings import Finding, FindingsArtifact
from icshps.schemas.profile import CandidateProfile, CertificationRecord, EducationRecord

AGENT_NAME = "credential_verification_agent_v1"


def build_credential_verification_findings(
    *,
    run_id: str,
    candidate_profile: CandidateProfile,
    credential_evidence_path: Path | None = None,
) -> FindingsArtifact:
    """Verify profile education and certifications against bundle-provided mock evidence."""

    evidence = _load_yaml_object(credential_evidence_path)
    findings: list[Finding] = []

    for education in candidate_profile.education:
        finding = _education_finding(
            candidate_profile=candidate_profile,
            education=education,
            evidence=evidence,
            evidence_path=credential_evidence_path,
            index=len(findings) + 1,
        )
        if finding is not None:
            findings.append(finding)

    for certification in candidate_profile.certifications:
        finding = _certification_finding(
            candidate_profile=candidate_profile,
            certification=certification,
            evidence=evidence,
            evidence_path=credential_evidence_path,
            index=len(findings) + 1,
        )
        if finding is not None:
            findings.append(finding)

    return FindingsArtifact(run_id=run_id, findings=findings)


def _education_finding(
    *,
    candidate_profile: CandidateProfile,
    education: EducationRecord,
    evidence: dict[str, Any],
    evidence_path: Path | None,
    index: int,
) -> Finding | None:
    match = _find_record(
        records=evidence.get("education_registry", []),
        keys=("institution", "degree"),
        values=(education.institution, education.degree or ""),
    )
    status = _status_for(match, education.verification_status)

    if education.is_international and status == "missing":
        return _finding(
            finding_id=f"credential-education-pending-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="International degree pending verification",
            description=f"Degree from '{education.institution}' needs mock registry verification.",
            reason="International education requires manual verification in the MVP workflow.",
            evidence_refs=_evidence_refs(
                profile_evidence=education.evidence,
                evidence_path=evidence_path,
                section="education_registry",
                snippet=education.institution,
            ),
            recommendation="Route to pending credential verification.",
        )

    if status == "verified":
        return _finding(
            finding_id=f"credential-education-verified-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.INFO,
            title="Education credential verified",
            description=f"Education credential at '{education.institution}' matched mock evidence.",
            reason="Bundle-provided mock evidence marks this education record as verified.",
            evidence_refs=_evidence_refs(
                education.evidence, evidence_path, "education_registry", education.institution
            ),
            recommendation="No credential exception for this education record.",
            requires_human_review=False,
        )

    if status in {"pending", "missing"}:
        return _finding(
            finding_id=f"credential-education-review-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="Education credential needs review",
            description=f"Education credential at '{education.institution}' is not verified in mock evidence.",
            reason="The mock credential registry does not confirm this education record.",
            evidence_refs=_evidence_refs(
                education.evidence, evidence_path, "education_registry", education.institution
            ),
            recommendation="Route to pending credential verification.",
        )

    return None


def _certification_finding(
    *,
    candidate_profile: CandidateProfile,
    certification: CertificationRecord,
    evidence: dict[str, Any],
    evidence_path: Path | None,
    index: int,
) -> Finding | None:
    if certification.confidence < 0.6 or certification.verification_status == "low_confidence":
        return _finding(
            finding_id=f"credential-certification-manual-review-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="Certification needs manual review",
            description=f"Certification '{certification.name}' has low extraction or document confidence.",
            reason="Low-confidence or handwritten certification evidence must be reviewed by a human.",
            evidence_refs=_evidence_refs(
                certification.evidence,
                evidence_path,
                "certification_registry",
                certification.name,
            ),
            recommendation="Route to manual credential review.",
        )

    match = _find_record(
        records=evidence.get("certification_registry", []),
        keys=("name", "issuer"),
        values=(certification.name, certification.issuer or ""),
    )
    status = _status_for(match, certification.verification_status)

    if status == "verified":
        return _finding(
            finding_id=f"credential-certification-verified-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.INFO,
            title="Certification verified",
            description=f"Certification '{certification.name}' matched mock authority evidence.",
            reason="Bundle-provided mock evidence marks this certification as verified.",
            evidence_refs=_evidence_refs(
                certification.evidence,
                evidence_path,
                "certification_registry",
                certification.name,
            ),
            recommendation="No credential exception for this certification.",
            requires_human_review=False,
        )

    if status == "revoked":
        return _finding(
            finding_id=f"credential-certification-revoked-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.BLOCKING,
            title="Certification marked revoked",
            description=f"Certification '{certification.name}' is marked revoked in mock evidence.",
            reason="Revoked certification evidence blocks automatic advancement pending human approval.",
            evidence_refs=_evidence_refs(
                certification.evidence,
                evidence_path,
                "certification_registry",
                certification.name,
            ),
            recommendation="Route as recommended rejection pending human approval.",
        )

    if status in {"pending", "missing"}:
        return _finding(
            finding_id=f"credential-certification-review-{index:03d}",
            candidate_profile=candidate_profile,
            severity=Severity.WARNING,
            title="Certification needs verification",
            description=f"Certification '{certification.name}' is not verified in mock evidence.",
            reason="The mock certification authority data does not confirm this certification.",
            evidence_refs=_evidence_refs(
                certification.evidence,
                evidence_path,
                "certification_registry",
                certification.name,
            ),
            recommendation="Route to pending credential verification.",
        )

    return None


def _finding(
    *,
    finding_id: str,
    candidate_profile: CandidateProfile,
    severity: Severity,
    title: str,
    description: str,
    reason: str,
    evidence_refs: list[EvidenceRef],
    recommendation: str,
    requires_human_review: bool = True,
) -> Finding:
    return Finding(
        id=finding_id,
        source_agent=AGENT_NAME,
        category=FindingCategory.CREDENTIAL,
        severity=severity,
        title=title,
        description=description,
        reason=reason,
        candidate_id=candidate_profile.candidate_id,
        application_id=candidate_profile.application_id,
        confidence=1.0,
        evidence=evidence_refs,
        recommendation=recommendation,
        requires_human_review=requires_human_review,
    )


def _load_yaml_object(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return {}

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _find_record(
    *, records: Any, keys: tuple[str, str], values: tuple[str, str]
) -> dict[str, Any] | None:
    if not isinstance(records, list):
        return None

    normalized_values = tuple(_normalize(value) for value in values if value)
    for record in records:
        if not isinstance(record, dict):
            continue
        record_values = tuple(
            _normalize(str(record.get(key, ""))) for key in keys if record.get(key)
        )
        if normalized_values and all(value in record_values for value in normalized_values):
            return record

    return None


def _status_for(record: dict[str, Any] | None, fallback: str | None) -> str:
    if record is not None:
        return str(record.get("status", "verified")).lower()
    if fallback:
        return fallback.lower()
    return "missing"


def _evidence_refs(
    profile_evidence: list[EvidenceRef],
    evidence_path: Path | None,
    section: str,
    snippet: str,
) -> list[EvidenceRef]:
    refs = list(profile_evidence)
    if evidence_path is not None:
        refs.append(
            EvidenceRef(
                source_path=evidence_path,
                source_type="mock_credential_evidence",
                section=section,
                text_snippet=snippet,
                confidence=1.0,
            )
        )
    return refs


def _normalize(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").split())
