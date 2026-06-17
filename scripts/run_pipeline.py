from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path


EXPECTED_ARTIFACTS: tuple[Path, ...] = (
    Path("inputs/context_packet.json"),
    Path("artifacts/intake_findings.json"),
    Path("artifacts/candidate_profile.json"),
    Path("artifacts/match_scores.json"),
    Path("artifacts/compliance_flags.md"),
    Path("artifacts/verification_findings.json"),
    Path("artifacts/anomaly_findings.json"),
    Path("artifacts/final_decision.json"),
    Path("artifacts/shortlist.csv"),
    Path("artifacts/hiring_packet.json"),
    Path("artifacts/metrics.json"),
    Path("artifacts/audit_log.md"),
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the ICSHPS backend pipeline for one Hiring Bundle.",
    )
    parser.add_argument(
        "bundle_path",
        type=Path,
        help="Path to a Hiring Bundle directory or a single clean PDF resume.",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Directory where run outputs are written. Default: runs",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=None,
        help="Optional deterministic run ID. If omitted, one is generated from the bundle.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing run directory before running.",
    )
    return parser


def _stable_run_id(bundle_path: Path) -> str:
    """
    Create a deterministic run ID from the bundle folder name and manifest content.

    This keeps demo runs stable without relying on timestamps.
    """
    manifest_path = bundle_path / "manifest.yaml"
    manifest_bytes = manifest_path.read_bytes()
    digest = hashlib.sha256(manifest_bytes).hexdigest()[:8]

    slug = bundle_path.name.strip().lower().replace(" ", "_").replace("-", "_")
    return f"{slug}_{digest}"


def _validate_bundle_path(bundle_path: Path) -> None:
    if not bundle_path.exists():
        raise ValueError(f"Input path does not exist: {bundle_path}")

    if not bundle_path.is_dir():
        raise ValueError(f"Hiring Bundle path must be a directory: {bundle_path}")

    manifest_path = bundle_path / "manifest.yaml"
    if not manifest_path.exists():
        raise ValueError(f"Hiring Bundle is missing manifest.yaml: {manifest_path}")


def _prepare_input_path(input_path: Path, runs_root: Path) -> Path:
    if not input_path.exists():
        raise ValueError(f"Input path does not exist: {input_path}")

    if input_path.is_dir():
        _validate_bundle_path(input_path)
        return input_path

    if input_path.suffix.lower() != ".pdf":
        raise ValueError(
            "Input path must be a Hiring Bundle directory or a clean PDF resume."
        )

    return _build_single_pdf_bundle(input_path=input_path, runs_root=runs_root)


def _build_single_pdf_bundle(*, input_path: Path, runs_root: Path) -> Path:
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()[:8]
    slug = input_path.stem.strip().lower().replace(" ", "_").replace("-", "_")
    bundle_path = runs_root / "_single_pdf_bundles" / f"{slug}_{digest}"

    if bundle_path.exists():
        shutil.rmtree(bundle_path)

    (bundle_path / "resumes").mkdir(parents=True)
    (bundle_path / "requirements").mkdir()
    (bundle_path / "policies").mkdir()
    (bundle_path / "mock_data").mkdir()

    resume_name = f"{slug or 'candidate'}_resume.pdf"
    shutil.copyfile(input_path, bundle_path / "resumes" / resume_name)

    (bundle_path / "job_description.md").write_text(
        "# Local Demo Role\n\nGeneral candidate screening role for single-PDF intake.\n",
        encoding="utf-8",
    )
    (bundle_path / "requirements" / "skills_matrix.yaml").write_text(
        "must_have: []\nnice_to_have: []\nmandatory_certifications: []\n",
        encoding="utf-8",
    )
    (bundle_path / "policies" / "eeo_policy.yaml").write_text(
        "risky_phrases: []\n",
        encoding="utf-8",
    )
    (bundle_path / "policies" / "credential_rules.yaml").write_text(
        "mandatory_certifications: []\n",
        encoding="utf-8",
    )
    (bundle_path / "mock_data" / "hris_master.yaml").write_text(
        "mock_hris_system: local_demo\nnotes:\n- Single-PDF local mock bundle.\n",
        encoding="utf-8",
    )
    (bundle_path / "manifest.yaml").write_text(
        _single_pdf_manifest(resume_name=resume_name, slug=slug or "candidate"),
        encoding="utf-8",
    )

    return bundle_path


def _single_pdf_manifest(*, resume_name: str, slug: str) -> str:
    candidate_id = f"candidate_{slug}_001"
    return f"""manifest_version: '1.0'
bundle:
  id: single_pdf_{slug}
  name: Single PDF Application - {slug}
  description: Deterministic local bundle generated from one PDF resume.
scenario:
  id: scenario_single_pdf_{slug}
  type: clean_standard_application
  expected_routing: Fast-track review
  tags:
  - single_pdf
  - clean
job:
  id: job_single_pdf_demo_001
  title: Local Demo Role
  department: Local Demo
  location: Local Demo
  employment_type: Full-time
candidates:
- id: {candidate_id}
  application_id: app_{slug}_001
  name: null
  target_job_id: job_single_pdf_demo_001
  resume_file: resumes/{resume_name}
required_inputs:
  job_description: job_description.md
  skills_matrix: requirements/skills_matrix.yaml
  eeo_policy: policies/eeo_policy.yaml
  credential_rules: policies/credential_rules.yaml
  hris_master: mock_data/hris_master.yaml
optional_inputs:
  linkedin_profiles: null
  application_history: null
  credential_evidence: null
  application_volume: null
execution:
  deterministic: true
  allow_missing_optional_inputs: true
  require_human_review_for_final_decision: true
notes:
- Generated by scripts/run_pipeline.py for single-PDF local demo intake.
"""


def _print_success(run_id: str, run_dir: Path) -> None:
    print("ICSHPS pipeline completed.")
    print(f"Run ID: {run_id}")
    print(f"Run directory: {run_dir}")
    print()
    print("Generated artifacts:")

    for relative_path in EXPECTED_ARTIFACTS:
        artifact_path = run_dir / relative_path
        if artifact_path.exists():
            print(f"- {relative_path}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    bundle_path = args.bundle_path.resolve()
    runs_root = args.runs_root.resolve()

    try:
        bundle_path = _prepare_input_path(bundle_path, runs_root)

        run_id = args.run_id or _stable_run_id(bundle_path)
        run_dir = runs_root / run_id

        if args.reset and run_dir.exists():
            shutil.rmtree(run_dir)

        # Keep this import inside main so invalid CLI usage fails quickly
        # without importing the whole pipeline.
        from icshps.graph.workflow import run_end_to_end_workflow

        run_end_to_end_workflow(
            bundle_path=bundle_path,
            runs_root=runs_root,
            run_id=run_id,
            reset=args.reset,
        )

        _print_success(run_id=run_id, run_dir=run_dir)
        return 0

    except Exception as exc:
        print(f"ICSHPS pipeline failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
