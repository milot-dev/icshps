from __future__ import annotations

from pathlib import Path
from typing import Any

from icshps.schemas import AtsPayload, AtsPayloadRecord, FinalDecisionArtifact
from icshps.utils.file_io import read_json_object, read_yaml_object


def build_ats_payload(
    *,
    final_decision: FinalDecisionArtifact,
    ats_export_path: Path | None = None,
    ats_requisition_path: Path | None = None,
) -> AtsPayload:
    """Build a deterministic local-only ATS payload from final routing output."""

    export_config = _read_mapping(ats_export_path)
    requisition = _read_mapping(ats_requisition_path)
    target_system = str(
        export_config.get("mock_ats_system")
        or export_config.get("target_system")
        or "local_demo_ats"
    )
    export_enabled = bool(export_config) and bool(
        export_config.get("export_enabled", True)
    )
    requisition_id = _requisition_id(
        export_config=export_config,
        requisition=requisition,
    )

    records = [
        AtsPayloadRecord(
            candidate_id=decision.candidate_id,
            application_id=decision.application_id,
            requisition_id=requisition_id,
            routing_category=decision.routing_category.value,
            status=_status_for_routing(decision.routing_category.value),
            score=decision.score,
            reason=decision.reason,
            blocking_finding_ids=sorted(decision.blocking_finding_ids),
            requires_human_approval=decision.requires_human_approval,
        )
        for decision in sorted(
            final_decision.decisions,
            key=lambda item: (item.candidate_id, item.application_id),
        )
    ]

    return AtsPayload(
        run_id=final_decision.run_id,
        bundle_id=final_decision.bundle_id,
        scenario_type=final_decision.scenario_type,
        target_system=target_system,
        dry_run=True,
        export_enabled=export_enabled,
        requisition=requisition,
        records=records,
        notes=[
            "Local mock payload only. No real ATS, HRIS, email, calendar, "
            "or background-check action is performed.",
            "Every routing recommendation requires human approval.",
            *_notes(export_config),
        ],
    )


def _read_mapping(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return {}

    if path.suffix.lower() == ".json":
        return read_json_object(path)

    return read_yaml_object(path)


def _requisition_id(
    *,
    export_config: dict[str, Any],
    requisition: dict[str, Any],
) -> str | None:
    value = (
        export_config.get("requisition_id")
        or requisition.get("requisition_id")
        or requisition.get("id")
    )
    return str(value) if value is not None else None


def _notes(export_config: dict[str, Any]) -> list[str]:
    raw_notes = export_config.get("notes", [])
    if isinstance(raw_notes, list):
        return [str(note) for note in raw_notes]
    if raw_notes:
        return [str(raw_notes)]
    return []


def _status_for_routing(routing_category: str) -> str:
    normalized = routing_category.lower()
    if "rejection" in normalized:
        return "review_recommended_rejection"
    if "interview" in normalized or "fast-track" in normalized:
        return "review_candidate"
    if "pending" in normalized:
        return "pending_verification"
    return "manual_review"
