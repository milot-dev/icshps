from pathlib import Path

from icshps.services.run_scaffolding import prepare_run_scaffold


def test_prepare_run_scaffold_creates_expected_structure(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    runs_root = tmp_path / "runs"

    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=runs_root,
    )

    assert scaffold.run_dir.exists()
    assert scaffold.inputs_dir.exists()
    assert scaffold.artifacts_dir.exists()
    assert scaffold.logs_dir.exists()
    assert scaffold.tmp_dir.exists()

    assert (scaffold.run_dir / "run_metadata.json").exists()
    assert (scaffold.run_dir / "artifact_manifest.json").exists()
    assert (scaffold.artifacts_dir / "audit_log.md").exists()
    assert (scaffold.artifacts_dir / "metrics.json").exists()
    assert (scaffold.logs_dir / "audit_events.jsonl").exists()


def test_prepare_run_scaffold_uses_stable_run_id(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    runs_root = tmp_path / "runs"

    first = prepare_run_scaffold(bundle_path=bundle_path, runs_root=runs_root)
    second = prepare_run_scaffold(bundle_path=bundle_path, runs_root=runs_root)

    assert first.run_id == second.run_id


def test_downstream_artifacts_are_reserved_but_not_falsely_created(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
    )

    assert not (scaffold.artifacts_dir / "candidate_profile.json").exists()
    assert not (scaffold.artifacts_dir / "match_scores.json").exists()
    assert not (scaffold.artifacts_dir / "compliance_flags.md").exists()