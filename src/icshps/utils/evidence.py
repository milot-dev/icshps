from __future__ import annotations

from icshps.schemas import EvidenceRef, Finding


def dedupe_evidence_refs(evidence_refs: list[EvidenceRef]) -> list[EvidenceRef]:
    deduped: list[EvidenceRef] = []
    seen: set[object] = set()

    for evidence in evidence_refs:
        key = evidence.evidence_id or (
            str(evidence.source_path),
            evidence.source_type,
            evidence.page_number,
            evidence.section,
            evidence.text_snippet,
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(evidence)

    return deduped


def evidence_from_findings(findings: list[Finding]) -> list[EvidenceRef]:
    evidence: list[EvidenceRef] = []

    for finding in findings:
        evidence.extend(finding.evidence)

    return dedupe_evidence_refs(evidence)
