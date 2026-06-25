from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from icshps.schemas.common import ICSHPSBaseModel
from icshps.utils.file_io import write_json

ReviewerAction = Literal[
    "approve_for_scheduling",
    "hold",
    "reject_after_human_review",
]

APPROVAL_SCHEMA_VERSION = "1.0"
APPROVAL_ARTIFACT_RELATIVE_PATH = Path("artifacts") / "reviewer_approvals.json"


class ReviewerApproval(ICSHPSBaseModel):
    """One local reviewer decision captured by the Streamlit UI."""

    candidate_id: str
    application_id: str
    action: ReviewerAction
    reviewer_name: str
    note: str = ""
    source_routing_category: str | None = None
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    created_at: str
    updated_at: str


class ReviewerApprovalsArtifact(ICSHPSBaseModel):
    """UI-owned local approval artifact for one completed run."""

    schema_version: str = APPROVAL_SCHEMA_VERSION
    run_id: str
    updated_at: str
    approvals: list[ReviewerApproval] = Field(default_factory=list)


@dataclass(frozen=True)
class ReviewerApprovalsResult:
    """Controlled read result for the optional reviewer approvals artifact."""

    artifact_path: Path
    run_id: str
    approvals: tuple[ReviewerApproval, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


def reviewer_approvals_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / APPROVAL_ARTIFACT_RELATIVE_PATH


def read_reviewer_approvals(run_dir: str | Path) -> ReviewerApprovalsResult:
    """Read optional Streamlit reviewer approvals without failing old runs."""

    resolved_run_dir = Path(run_dir)
    path = reviewer_approvals_path(resolved_run_dir)
    run_id = resolved_run_dir.name

    if not path.exists():
        return ReviewerApprovalsResult(
            artifact_path=path,
            run_id=run_id,
            approvals=(),
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifact = ReviewerApprovalsArtifact.model_validate(payload)
    except (json.JSONDecodeError, OSError, TypeError, ValueError, ValidationError) as exc:
        return ReviewerApprovalsResult(
            artifact_path=path,
            run_id=run_id,
            approvals=(),
            errors=(f"Invalid reviewer approvals artifact at {path}: {exc}",),
        )

    if artifact.run_id != run_id:
        return ReviewerApprovalsResult(
            artifact_path=path,
            run_id=run_id,
            approvals=tuple(artifact.approvals),
            errors=(
                f"Reviewer approvals artifact run_id '{artifact.run_id}' "
                f"does not match run directory '{run_id}'.",
            ),
        )

    return ReviewerApprovalsResult(
        artifact_path=path,
        run_id=run_id,
        approvals=tuple(artifact.approvals),
    )


def upsert_reviewer_approval(
    *,
    run_dir: str | Path,
    candidate_id: str,
    application_id: str,
    action: ReviewerAction,
    reviewer_name: str,
    note: str = "",
    source_routing_category: str | None = None,
    score: float | None = None,
) -> ReviewerApproval:
    """Create or replace one reviewer approval for a candidate application."""

    resolved_run_dir = Path(run_dir)
    result = read_reviewer_approvals(resolved_run_dir)
    if not result.ok:
        raise ValueError(result.errors[0])

    now = _utc_now()
    existing_by_key = {
        (approval.candidate_id, approval.application_id): approval
        for approval in result.approvals
    }
    key = (candidate_id, application_id)
    existing = existing_by_key.get(key)

    approval = ReviewerApproval(
        candidate_id=candidate_id,
        application_id=application_id,
        action=action,
        reviewer_name=reviewer_name,
        note=note,
        source_routing_category=source_routing_category,
        score=score,
        created_at=existing.created_at if existing else now,
        updated_at=now,
    )
    existing_by_key[key] = approval

    artifact = ReviewerApprovalsArtifact(
        run_id=resolved_run_dir.name,
        updated_at=now,
        approvals=sorted(
            existing_by_key.values(),
            key=lambda item: (item.candidate_id, item.application_id),
        ),
    )
    write_json(reviewer_approvals_path(resolved_run_dir), artifact)
    return approval


def approval_action_label(action: str | None) -> str:
    labels = {
        "approve_for_scheduling": "Approved for scheduling",
        "hold": "Hold",
        "reject_after_human_review": "Rejected after human review",
    }
    return labels.get(action or "", "Not reviewed")


def approvals_by_application(
    approvals: tuple[ReviewerApproval, ...] | list[ReviewerApproval],
) -> dict[tuple[str, str], ReviewerApproval]:
    return {
        (approval.candidate_id, approval.application_id): approval
        for approval in approvals
    }


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
