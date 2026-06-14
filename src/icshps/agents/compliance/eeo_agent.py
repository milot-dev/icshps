from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from icshps.schemas.common import EvidenceRef, FindingCategory, Severity
from icshps.schemas.findings import Finding, FindingsArtifact

AGENT_NAME = "eeo_compliance_agent_v1"


@dataclass(frozen=True)
class _Rule:
    code: str
    category: str
    pattern: re.Pattern[str]
    title: str
    reason: str
    severity: Severity = Severity.WARNING


DEFAULT_RULES: tuple[_Rule, ...] = (
    _Rule(
        code="age-recent-graduate",
        category="age_specific_language",
        pattern=re.compile(r"\brecent\s+graduate(s)?\b", re.IGNORECASE),
        title="Age-specific job description language",
        reason="'Recent graduate' can create age-related adverse impact risk.",
    ),
    _Rule(
        code="age-digital-native",
        category="age_specific_language",
        pattern=re.compile(r"\bdigital\s+native(s)?\b", re.IGNORECASE),
        title="Age-specific job description language",
        reason="'Digital native' may imply a preference for younger applicants.",
    ),
    _Rule(
        code="age-young-energetic",
        category="age_specific_language",
        pattern=re.compile(r"\byoung\s+and\s+energetic\b", re.IGNORECASE),
        title="Age-specific job description language",
        reason="'Young and energetic' can imply age preference.",
    ),
    _Rule(
        code="protected-gender",
        category="protected_characteristic_language",
        pattern=re.compile(r"\b(male|female|men only|women only)\b", re.IGNORECASE),
        title="Protected-characteristic language",
        reason="Gender-specific requirements should not appear in a merit-based JD.",
    ),
    _Rule(
        code="protected-family-status",
        category="protected_characteristic_language",
        pattern=re.compile(r"\b(single|married|without children)\b", re.IGNORECASE),
        title="Protected-characteristic language",
        reason="Family or marital status language can create compliance risk.",
    ),
    _Rule(
        code="protected-disability",
        category="protected_characteristic_language",
        pattern=re.compile(r"\bable-bodied\b", re.IGNORECASE),
        title="Protected-characteristic language",
        reason="Disability-related wording should be reviewed for job necessity.",
    ),
)


def build_eeo_compliance_findings(
    *,
    run_id: str,
    job_description_path: Path,
    job_title: str | None = None,
    eeo_policy_path: Path | None = None,
) -> FindingsArtifact:
    """Scan a job description for deterministic EEO and adverse-impact findings."""

    jd_text = job_description_path.read_text(encoding="utf-8")
    rules = DEFAULT_RULES + _load_policy_rules(eeo_policy_path)
    findings: list[Finding] = []

    for line_number, line in enumerate(jd_text.splitlines(), start=1):
        for rule in rules:
            if not rule.pattern.search(line):
                continue

            findings.append(
                _finding(
                    rule=rule,
                    index=len(findings) + 1,
                    source_path=job_description_path,
                    line_number=line_number,
                    snippet=line.strip(),
                )
            )

    findings.extend(
        _experience_level_findings(
            job_description_path=job_description_path,
            job_title=job_title,
            starting_index=len(findings) + 1,
            jd_text=jd_text,
        )
    )

    return FindingsArtifact(run_id=run_id, findings=findings)


def _finding(
    *,
    rule: _Rule,
    index: int,
    source_path: Path,
    line_number: int,
    snippet: str,
) -> Finding:
    return Finding(
        id=f"eeo-{rule.code}-{index:03d}",
        source_agent=AGENT_NAME,
        category=FindingCategory.COMPLIANCE,
        severity=rule.severity,
        title=rule.title,
        description=f"{rule.reason} Flagged phrase appears on line {line_number}.",
        reason=rule.reason,
        confidence=1.0,
        evidence=[
            EvidenceRef(
                source_path=source_path,
                source_type="job_description",
                section=f"line:{line_number}",
                text_snippet=snippet,
                confidence=1.0,
            )
        ],
        recommendation="Review and rewrite the job description before publishing.",
        requires_human_review=True,
    )


def _experience_level_findings(
    *,
    job_description_path: Path,
    job_title: str | None,
    starting_index: int,
    jd_text: str,
) -> list[Finding]:
    level_text = (job_title or "").lower()
    entry_level_role = any(token in level_text for token in ("intern", "junior", "entry"))
    findings: list[Finding] = []
    pattern = re.compile(r"\b(\d{1,2})\+?\s+years?\s+(of\s+)?experience\b", re.IGNORECASE)

    for line_number, line in enumerate(jd_text.splitlines(), start=1):
        for match in pattern.finditer(line):
            years = int(match.group(1))
            if years < 10 and not (entry_level_role and years >= 5):
                continue

            rule = _Rule(
                code=f"experience-years-{years}",
                category="age_specific_language",
                pattern=pattern,
                title="Experience threshold needs EEO review",
                reason=(
                    f"{years}+ years of experience may be excessive for this role level."
                    if entry_level_role
                    else f"{years}+ years of experience should be validated as job-related."
                ),
            )
            findings.append(
                _finding(
                    rule=rule,
                    index=starting_index + len(findings),
                    source_path=job_description_path,
                    line_number=line_number,
                    snippet=line.strip(),
                )
            )

    return findings


def _load_policy_rules(policy_path: Path | None) -> tuple[_Rule, ...]:
    if policy_path is None or not policy_path.exists() or policy_path.stat().st_size == 0:
        return ()

    payload = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    rules_payload = payload.get("risky_phrases", [])
    rules: list[_Rule] = []

    for index, item in enumerate(rules_payload, start=1):
        phrase = str(item.get("phrase", "")).strip()
        if not phrase:
            continue

        rules.append(
            _Rule(
                code=f"policy-{index:03d}",
                category=str(item.get("category", "policy_defined_language")),
                pattern=re.compile(re.escape(phrase), re.IGNORECASE),
                title=str(item.get("title", "Policy-defined EEO language")),
                reason=str(item.get("reason", "Phrase is listed in the EEO policy pack.")),
                severity=Severity(str(item.get("severity", Severity.WARNING.value))),
            )
        )

    return tuple(rules)
