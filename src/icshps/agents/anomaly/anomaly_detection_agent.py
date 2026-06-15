from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from icshps.schemas import EvidenceRef, FindingCategory, Severity, Finding, FindingsArtifact

AGENT_NAME = "surge_mode_detection_v1"


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
                        text_snippet=_build_evidence_snippet(surge_conditions, volume_data),
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
            return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        elif path.suffix.lower() == ".json":
            return json.loads(path.read_text(encoding="utf-8")) or {}
    except (ValueError, yaml.YAMLError):
        return {}

    return {}


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
