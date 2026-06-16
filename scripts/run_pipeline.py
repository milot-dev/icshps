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
        help="Path to the Hiring Bundle directory.",
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
        raise ValueError(f"Hiring Bundle does not exist: {bundle_path}")

    if not bundle_path.is_dir():
        raise ValueError(f"Hiring Bundle path must be a directory: {bundle_path}")

    manifest_path = bundle_path / "manifest.yaml"
    if not manifest_path.exists():
        raise ValueError(f"Hiring Bundle is missing manifest.yaml: {manifest_path}")


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
        _validate_bundle_path(bundle_path)

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