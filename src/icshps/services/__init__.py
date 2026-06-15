"""Shared backend services for ICSHPS runs, bundles, artifacts, and stage results."""

from icshps.services.artifact_catalog import (
    ArtifactCatalogItem,
    ArtifactCatalogResult,
    read_artifact_catalog,
)
from icshps.services.artifact_writer import (
    artifact_path,
    mark_artifacts_created,
    read_json_artifact,
    write_json_artifact,
)
from icshps.services.bundle_loader import (
    LoadedBundle,
    load_hiring_bundle,
    snapshot_manifest_to_run,
)
from icshps.services.compliance_flags_writer import (
    build_compliance_flags_markdown,
    write_compliance_flags_md,
)
from icshps.services.run_scaffolding import (
    RunScaffold,
    compute_bundle_fingerprint,
    prepare_run_scaffold,
)
from icshps.services.stage_result import AgentStageResult

__all__ = [
    "AgentStageResult",
    "ArtifactCatalogItem",
    "ArtifactCatalogResult",
    "LoadedBundle",
    "RunScaffold",
    "artifact_path",
    "build_compliance_flags_markdown",
    "compute_bundle_fingerprint",
    "load_hiring_bundle",
    "mark_artifacts_created",
    "prepare_run_scaffold",
    "read_artifact_catalog",
    "read_json_artifact",
    "snapshot_manifest_to_run",
    "write_compliance_flags_md",
    "write_json_artifact",
]