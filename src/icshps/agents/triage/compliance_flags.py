from __future__ import annotations

from icshps.schemas.common import FindingCategory
from icshps.schemas.decision import FinalDecisionArtifact
from icshps.schemas.findings import Finding


def render_compliance_flags_markdown(
    *,
    run_id: str,
    findings: list[Finding],
    decisions: FinalDecisionArtifact | None = None,
) -> str:
    """Render reviewer-friendly compliance_flags.md content."""

    lines = [
        "# Compliance Flags",
        "",
        f"Run ID: `{run_id}`",
        "",
        "All routing recommendations require human approval. This artifact is not a final hiring decision.",
        "",
    ]
    lines.extend(_section("EEO and Legal Compliance", findings, {FindingCategory.COMPLIANCE}))
    lines.extend(_section("Credential Verification", findings, {FindingCategory.CREDENTIAL, FindingCategory.MATCHING}))
    lines.extend(
        _section(
            "Anomaly and Consistency Review",
            findings,
            {FindingCategory.ANOMALY, FindingCategory.LINKEDIN_CONSISTENCY},
        )
    )

    if decisions is not None:
        lines.extend(["## Routing Recommendations", ""])
        for decision in decisions.decisions:
            lines.extend(
                [
                    f"### {decision.candidate_id}",
                    "",
                    f"- Application: `{decision.application_id}`",
                    f"- Routing category: `{decision.routing_category.value}`",
                    f"- Reason: {decision.reason}",
                    f"- Human approval required: `{decision.requires_human_approval}`",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def _section(
    title: str,
    findings: list[Finding],
    categories: set[FindingCategory],
) -> list[str]:
    selected = [finding for finding in findings if finding.category in categories]
    lines = [f"## {title}", ""]

    if not selected:
        lines.extend(["No findings.", ""])
        return lines

    for finding in selected:
        evidence = finding.evidence[0] if finding.evidence else None
        snippet = evidence.text_snippet if evidence else "No evidence snippet provided."
        source = evidence.source_path if evidence else "No evidence source provided."
        lines.extend(
            [
                f"### {finding.title}",
                "",
                f"- Severity: `{finding.severity.value}`",
                f"- Candidate: `{finding.candidate_id or 'bundle-level'}`",
                f"- Reason: {finding.reason or finding.description}",
                f"- Evidence source: `{source}`",
                f"- Evidence snippet: {snippet}",
                f"- Recommendation: {finding.recommendation or 'Human review required.'}",
                "",
            ]
        )

    return lines
