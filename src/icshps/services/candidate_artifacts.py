from __future__ import annotations

from icshps.schemas import CandidateProfile
from icshps.services.artifact_writer import read_json_artifact
from icshps.services.run_scaffolding import RunScaffold


def read_candidate_profiles(scaffold: RunScaffold) -> list[CandidateProfile]:
    profile_payload = read_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
    )

    if profile_payload is None:
        return []

    return [CandidateProfile.model_validate(profile_payload)]
