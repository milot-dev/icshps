from __future__ import annotations

import json

from icshps.schemas import CandidateProfile
from icshps.services.artifact_writer import artifact_path, read_json_artifact
from icshps.services.run_scaffolding import RunScaffold


def read_candidate_profiles(scaffold: RunScaffold) -> list[CandidateProfile]:
    try:
        profiles_path = artifact_path(scaffold, "candidate_profiles")
    except KeyError:
        profiles_path = None

    if profiles_path is not None and profiles_path.exists():
        profiles_payload = json.loads(profiles_path.read_text(encoding="utf-8"))
        if not isinstance(profiles_payload, list):
            raise ValueError(f"Expected JSON array at {profiles_path}")

        return [
            CandidateProfile.model_validate(profile_payload)
            for profile_payload in profiles_payload
        ]

    profile_payload = read_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
    )

    if profile_payload is None:
        return []

    return [CandidateProfile.model_validate(profile_payload)]
