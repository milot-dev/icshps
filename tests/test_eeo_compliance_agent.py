from pathlib import Path

from icshps.agents.compliance import build_eeo_compliance_findings


def test_eeo_agent_flags_age_specific_and_protected_language(tmp_path: Path) -> None:
    jd_path = tmp_path / "job_description.md"
    jd_path.write_text(
        "\n".join(
            [
                "# Junior AI Engineer",
                "We are looking for a recent graduate.",
                "The ideal candidate is a digital native.",
                "This role is open to male applicants only.",
                "Requires 10+ years of experience.",
            ]
        ),
        encoding="utf-8",
    )

    artifact = build_eeo_compliance_findings(
        run_id="run_001",
        job_description_path=jd_path,
        job_title="Junior AI Engineer",
    )

    assert artifact.run_id == "run_001"
    assert [finding.id for finding in artifact.findings] == [
        "eeo-age-recent-graduate-001",
        "eeo-age-digital-native-002",
        "eeo-protected-gender-003",
        "eeo-experience-years-10-004",
    ]
    assert all(finding.category == "compliance" for finding in artifact.findings)
    assert all(finding.evidence for finding in artifact.findings)


def test_eeo_agent_supports_policy_defined_phrases(tmp_path: Path) -> None:
    jd_path = tmp_path / "job_description.md"
    policy_path = tmp_path / "eeo_policy.yaml"
    jd_path.write_text("Must be a culture fit.\n", encoding="utf-8")
    policy_path.write_text(
        """
risky_phrases:
  - phrase: culture fit
    category: protected_characteristic_language
    title: Ambiguous culture-fit language
    reason: Culture-fit wording can hide non-merit screening criteria.
    severity: warning
""",
        encoding="utf-8",
    )

    artifact = build_eeo_compliance_findings(
        run_id="run_001",
        job_description_path=jd_path,
        eeo_policy_path=policy_path,
    )

    assert len(artifact.findings) == 1
    assert artifact.findings[0].id == "eeo-policy-001-001"
    assert "Culture-fit" in artifact.findings[0].reason
