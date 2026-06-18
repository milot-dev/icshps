from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field

from icshps.schemas.common import ICSHPSBaseModel


class RunStatus(str, Enum):
    """Lifecycle status for one local pipeline run."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactStatus(str, Enum):
    """Whether an artifact exists now or is only reserved for a later agent."""

    CREATED = "created"
    RESERVED = "reserved"


class RunMetadata(ICSHPSBaseModel):
    """Stable metadata describing one ICSHPS run folder."""

    run_id: str
    bundle_path: Path
    run_dir: Path
    input_fingerprint: str
    status: RunStatus = RunStatus.CREATED
    deterministic: bool = True
    schema_version: str = "1.0"


class ArtifactRef(ICSHPSBaseModel):
    """A stable artifact path owned by a member or pipeline stage."""

    path: Path
    owner: str
    description: str
    status: ArtifactStatus = ArtifactStatus.RESERVED
    required_for_mvp: bool = True


class RunArtifactManifest(ICSHPSBaseModel):
    """Registry of expected files for one run."""

    run_id: str
    artifacts: dict[str, ArtifactRef] = Field(default_factory=dict)