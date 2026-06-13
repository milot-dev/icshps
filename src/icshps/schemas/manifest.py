from __future__ import annotations

from pydantic import Field

from icshps.schemas.common import ICSHPSBaseModel
from icshps.schemas.context import (
    BundleInfo,
    CandidateApplication,
    JobInfo,
    OptionalInputPaths,
    RequiredInputPaths,
    ScenarioInfo,
)

"""Schemas that describe the manifest.yaml Hiring Bundle contract."""


class ManifestExecutionSettings(ICSHPSBaseModel):
    """Execution flags declared by a Hiring Bundle manifest."""

    deterministic: bool = True
    allow_missing_optional_inputs: bool = True
    require_human_review_for_final_decision: bool = True


class HiringBundleManifest(ICSHPSBaseModel):
    """Validated representation of one Hiring Bundle manifest.yaml file."""

    manifest_version: str = "1.0"
    bundle: BundleInfo
    scenario: ScenarioInfo
    job: JobInfo
    candidates: list[CandidateApplication] = Field(min_length=1)
    required_inputs: RequiredInputPaths
    optional_inputs: OptionalInputPaths = Field(default_factory=OptionalInputPaths)
    execution: ManifestExecutionSettings = Field(default_factory=ManifestExecutionSettings)
    notes: list[str] = Field(default_factory=list)
