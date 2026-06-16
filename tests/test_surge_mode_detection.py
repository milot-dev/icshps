from __future__ import annotations

from pathlib import Path


from icshps.agents.anomaly import build_surge_mode_findings
from icshps.schemas.common import FindingCategory, Severity


def test_surge_mode_detection_with_no_volume_file_returns_empty_findings() -> None:
    findings_artifact = build_surge_mode_findings(run_id="run123", application_volume_path=None)

    assert findings_artifact.run_id == "run123"
    assert len(findings_artifact.findings) == 0


def test_surge_mode_detection_with_bulk_application_flag(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.yaml"
    volume_file.write_text(
        """
bulk_application_flag: true
application_count: 75
surge_threshold: 50
""",
        encoding="utf-8",
    )

    findings_artifact = build_surge_mode_findings(
        run_id="run123",
        application_volume_path=volume_file,
    )

    assert len(findings_artifact.findings) == 1
    finding = findings_artifact.findings[0]
    assert finding.title == "Surge processing mode activated"
    assert finding.category == FindingCategory.ANOMALY
    assert finding.severity == Severity.INFO
    assert "bulk_application_flag" in finding.description
    assert finding.confidence == 1.0
    assert finding.requires_human_review is False


def test_surge_mode_detection_with_high_application_count(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.yaml"
    volume_file.write_text(
        """
bulk_application_flag: false
application_count: 150
surge_threshold: 50
viral_job_post: false
""",
        encoding="utf-8",
    )

    findings_artifact = build_surge_mode_findings(
        run_id="run123",
        application_volume_path=volume_file,
    )

    assert len(findings_artifact.findings) == 1
    finding = findings_artifact.findings[0]
    assert "application_count" in finding.description


def test_surge_mode_detection_with_viral_indicator(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.yaml"
    volume_file.write_text(
        """
bulk_application_flag: false
application_count: 30
surge_threshold: 50
viral_job_post: true
""",
        encoding="utf-8",
    )

    findings_artifact = build_surge_mode_findings(
        run_id="run123",
        application_volume_path=volume_file,
    )

    assert len(findings_artifact.findings) == 1
    finding = findings_artifact.findings[0]
    assert "viral_job_post" in finding.description


def test_surge_mode_detection_with_no_surge_conditions(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.yaml"
    volume_file.write_text(
        """
bulk_application_flag: false
application_count: 10
surge_threshold: 50
viral_job_post: false
""",
        encoding="utf-8",
    )

    findings_artifact = build_surge_mode_findings(
        run_id="run123",
        application_volume_path=volume_file,
    )

    assert len(findings_artifact.findings) == 0


def test_surge_mode_detection_with_json_format(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.json"
    volume_file.write_text(
        """{
  "bulk_application_flag": true,
  "application_count": 100,
  "surge_threshold": 50,
  "viral_job_post": false
}""",
        encoding="utf-8",
    )

    findings_artifact = build_surge_mode_findings(
        run_id="run123",
        application_volume_path=volume_file,
    )

    assert len(findings_artifact.findings) == 1


def test_surge_mode_detection_is_deterministic(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.yaml"
    volume_file.write_text(
        """
bulk_application_flag: true
application_count: 75
surge_threshold: 50
viral_job_post: true
""",
        encoding="utf-8",
    )

    first = build_surge_mode_findings(run_id="run123", application_volume_path=volume_file)
    second = build_surge_mode_findings(run_id="run123", application_volume_path=volume_file)

    assert first.findings[0].id == second.findings[0].id
    assert first.findings[0].description == second.findings[0].description
    assert first.findings[0].evidence[0].text_snippet == second.findings[0].evidence[0].text_snippet


def test_surge_mode_finding_includes_evidence_pointers(tmp_path: Path) -> None:
    volume_file = tmp_path / "application_volume.yaml"
    volume_file.write_text(
        """
bulk_application_flag: true
application_count: 200
surge_threshold: 50
""",
        encoding="utf-8",
    )

    findings_artifact = build_surge_mode_findings(
        run_id="run123",
        application_volume_path=volume_file,
    )

    finding = findings_artifact.findings[0]
    assert len(finding.evidence) == 1
    assert finding.evidence[0].source_type == "application_volume_metadata"
    assert finding.evidence[0].source_path == volume_file
    assert finding.evidence[0].confidence == 1.0
