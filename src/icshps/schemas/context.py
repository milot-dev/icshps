from __future__ import annotations

from pathlib import Path

from pydantic import Field

from icshps.schemas.common import EvidenceRef, ICSHPSBaseModel

"""Schemas for Hiring Bundle context and validated run inputs."""

class BundleInfo(ICSHPSBaseModel):
    """Metadata describing one Hiring Bundle."""
    
    id: str
    name: str
    description: str | None = None


class ScenarioInfo(ICSHPSBaseModel):
    """Scenario metadata used for testing and expected routing behavior."""

    id: str
    type: str
    expected_routing: str | None = None
    tags: list[str] = Field(default_factory=list)


class JobInfo(ICSHPSBaseModel):
    """Basic job metadata associated with the Hiring Bundle."""

    id: str
    title: str
    department: str | None = None
    location: str | None = None
    employment_type: str | None = None


class CandidateApplication(ICSHPSBaseModel):
    """One candidate application listed in the Hiring Bundle manifest."""

    id: str
    application_id: str
    name: str | None = None
    target_job_id: str
    resume_file: Path


class RequiredInputPaths(ICSHPSBaseModel):
    """Required file paths that must exist for a Hiring Bundle to run."""

    job_description: Path
    skills_matrix: Path
    eeo_policy: Path
    credential_rules: Path
    hris_master: Path


class OptionalInputPaths(ICSHPSBaseModel):
    """Optional mock input paths used only by specific demo scenarios."""

    linkedin_profiles: Path | None = None
    application_history: Path | None = None
    credential_evidence: Path | None = None
    application_volume: Path | None = None


class BundleContext(ICSHPSBaseModel):
    """Validated context packet passed from intake to downstream agents."""
    
    run_id: str
    bundle_path: Path
    bundle: BundleInfo
    scenario: ScenarioInfo
    job: JobInfo
    candidates: list[CandidateApplication]
    required_inputs: RequiredInputPaths
    optional_inputs: OptionalInputPaths
    evidence_index: list[EvidenceRef] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    is_ready: bool = False