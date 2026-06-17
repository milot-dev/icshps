from __future__ import annotations

from enum import Enum
from pathlib import Path

from icshps.schemas.common import FindingCategory, Severity
from icshps.schemas.findings import Finding, FindingsArtifact

_SEVERITY_ORDER: dict[str, int] = {
    Severity.BLOCKING.value: 0,
    Severity.ERROR.value: 1,
    Severity.WARNING.value: 2,
    Severity.INFO.value: 3,
}


def build_compliance_flags_markdown(artifact: FindingsArtifact) -> str:
    """Render a deterministic compliance_flags.md from a FindingsArtifact."""

    header = ["# Compliance Flags", f"Run ID: {artifact.run_id}", ""]
    relevant_findings = _filter_relevant_findings(artifact.findings)

    if not relevant_findings:
        return "\n".join(
            header
            + [
                "No compliance flags were detected.",
                "",
            ]
        )

    sections: list[str] = []
    groups = _group_findings(relevant_findings)

    for group_name, findings in groups.items():
        sections.append(f"## {group_name}")
        sections.append("")

        for finding in findings:
            sections.extend(_render_finding(finding))
            sections.append("")

    return "\n".join(header + sections)


def write_compliance_flags_md(path: Path, artifact: FindingsArtifact) -> None:
    """Write the compliance_flags.md artifact to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_compliance_flags_markdown(artifact), encoding="utf-8")


def _filter_relevant_findings(findings: list[Finding]) -> list[Finding]:
    relevant: list[Finding] = []
    for finding in findings:
        if (
            _is_eeo_finding(finding)
            or _is_mandatory_certification_finding(finding)
            or _is_credential_finding(finding)
            or _is_anomaly_finding(finding)
            or _is_routing_finding(finding)
        ):
            relevant.append(finding)
    return sorted(relevant, key=_finding_sort_key)


def _is_eeo_finding(finding: Finding) -> bool:
    return (
        finding.category == FindingCategory.COMPLIANCE
        or finding.source_agent == "eeo_compliance_agent_v1"
        or "eeo" in finding.source_agent
    )


def _is_mandatory_certification_finding(finding: Finding) -> bool:
    return (
        finding.source_agent == "mandatory_certification_check_v1"
        or finding.category == FindingCategory.MATCHING
        and "certification" in finding.title.lower()
    )


def _is_credential_finding(finding: Finding) -> bool:
    return finding.category == FindingCategory.CREDENTIAL


def _is_anomaly_finding(finding: Finding) -> bool:
    return (
        finding.category == FindingCategory.ANOMALY
        or finding.category == FindingCategory.LINKEDIN_CONSISTENCY
    )


def _is_routing_finding(finding: Finding) -> bool:
    return finding.category == FindingCategory.TRIAGE


def _group_findings(findings: list[Finding]) -> dict[str, list[Finding]]:
    groups: dict[str, list[Finding]] = {
        "EEO compliance findings": [],
        "Mandatory certification findings": [],
        "Credential verification summary": [],
        "Anomaly summary": [],
        "Routing recommendation summary": [],
    }

    for finding in findings:
        if _is_mandatory_certification_finding(finding):
            groups["Mandatory certification findings"].append(finding)
        elif _is_eeo_finding(finding):
            groups["EEO compliance findings"].append(finding)
        elif _is_credential_finding(finding):
            groups["Credential verification summary"].append(finding)
        elif _is_anomaly_finding(finding):
            groups["Anomaly summary"].append(finding)
        elif _is_routing_finding(finding):
            groups["Routing recommendation summary"].append(finding)

    return {name: groups[name] for name in groups if groups[name]}


def _finding_sort_key(finding: Finding) -> tuple[int, str, str, str]:
    severity = str(finding.severity).lower()
    severity_rank = _SEVERITY_ORDER.get(severity, 99)
    category = finding.category.value if isinstance(finding.category, Enum) else str(finding.category)
    return (severity_rank, category, finding.title or "", finding.id or "")


def _render_finding(finding: Finding) -> list[str]:
    lines = [f"### {finding.title}", ""]
    lines.append(f"- id: `{finding.id}`")
    lines.append(f"- source_agent: `{finding.source_agent}`")
    lines.append(f"- category: `{finding.category.value if isinstance(finding.category, Enum) else finding.category}`")
    lines.append(f"- severity: `{finding.severity.value if isinstance(finding.severity, Enum) else finding.severity}`")
    lines.append(f"- message: {finding.description}")
    if finding.reason:
        lines.append(f"- reason: {finding.reason}")
    if finding.recommendation:
        lines.append(f"- recommendation: {finding.recommendation}")
    lines.append(f"- confidence: {finding.confidence:.2f}")
    lines.append(f"- requires_human_review: {'Yes' if finding.requires_human_review else 'No'}")
    lines.append("- evidence:")

    if finding.evidence:
        for evidence in sorted(finding.evidence, key=_evidence_sort_key):
            lines.append(_render_evidence(evidence))
    else:
        lines.append("  - None recorded.")

    return lines


def _evidence_sort_key(evidence: object) -> tuple[str, str, str | float]:
    source_type = getattr(evidence, "source_type", "") or ""
    section = getattr(evidence, "section", "") or ""
    snippet = getattr(evidence, "text_snippet", "") or ""
    confidence = getattr(evidence, "confidence", 0.0) or 0.0
    return (source_type, section, snippet, confidence)


def _render_evidence(evidence: object) -> str:
    source_path = getattr(evidence, "source_path", None)
    path_text = str(source_path) if source_path is not None else "unknown"
    source_type = getattr(evidence, "source_type", "unknown")
    section = getattr(evidence, "section", "unknown")
    snippet = getattr(evidence, "text_snippet", "")
    confidence = getattr(evidence, "confidence", None)

    confidence_text = f" (confidence: {confidence:.2f})" if confidence is not None else ""
    snippet_text = f' "{snippet}"' if snippet else ""

    return f"  - {source_type}:{section} from {path_text}{snippet_text}{confidence_text}"
