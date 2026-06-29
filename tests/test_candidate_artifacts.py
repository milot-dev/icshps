import json
from pathlib import Path

from icshps.agents.extraction import build_synthetic_candidate_profile
from icshps.services import prepare_run_scaffold, write_json_artifact
from icshps.services.candidate_artifacts import read_candidate_profiles


def test_read_candidate_profiles_returns_empty_list_when_missing(tmp_path: Path) -> None:
    scaffold = prepare_test_scaffold(tmp_path)

    assert read_candidate_profiles(scaffold) == []


def test_read_candidate_profiles_falls_back_to_single_profile_artifact(
    tmp_path: Path,
) -> None:
    scaffold = prepare_test_scaffold(tmp_path)
    profile = build_synthetic_candidate_profile(candidate_id="cand_single")

    write_json_artifact(scaffold=scaffold, artifact_key="candidate_profile", payload=profile)

    profiles = read_candidate_profiles(scaffold)

    assert [profile.candidate_id for profile in profiles] == ["cand_single"]


def test_read_candidate_profiles_falls_back_when_multi_profile_key_is_missing(
    tmp_path: Path,
) -> None:
    scaffold = prepare_test_scaffold(tmp_path)
    profile = build_synthetic_candidate_profile(candidate_id="cand_old_run")

    write_json_artifact(scaffold=scaffold, artifact_key="candidate_profile", payload=profile)
    manifest = json.loads(scaffold.artifact_manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"].pop("candidate_profiles")
    scaffold.artifact_manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    profiles = read_candidate_profiles(scaffold)

    assert [profile.candidate_id for profile in profiles] == ["cand_old_run"]


def test_read_candidate_profiles_prefers_multi_profile_artifact(
    tmp_path: Path,
) -> None:
    scaffold = prepare_test_scaffold(tmp_path)
    single_profile = build_synthetic_candidate_profile(candidate_id="cand_single")
    profiles_payload = [
        build_synthetic_candidate_profile(candidate_id="cand_first").model_dump(
            mode="json"
        ),
        build_synthetic_candidate_profile(candidate_id="cand_second").model_dump(
            mode="json"
        ),
    ]

    write_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
        payload=single_profile,
    )
    write_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profiles",
        payload=profiles_payload,
    )

    profiles = read_candidate_profiles(scaffold)

    assert [profile.candidate_id for profile in profiles] == [
        "cand_first",
        "cand_second",
    ]


def prepare_test_scaffold(tmp_path: Path):
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: candidate_artifacts_test\n",
        encoding="utf-8",
    )
    return prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")
