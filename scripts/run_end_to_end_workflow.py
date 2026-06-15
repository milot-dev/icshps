from __future__ import annotations

from pathlib import Path

from icshps.graph import run_end_to_end_workflow


def main() -> None:
    result = run_end_to_end_workflow(
        Path("data/hiring_bundles/clean_standard_application")
    )

    print(f"Status: {result.status}")
    print(f"Run ID: {result.run_id}")
    print(f"Run dir: {result.run_dir}")
    print(f"Created artifacts: {result.created_artifacts}")
    print(f"Pending artifacts: {result.pending_artifacts}")
    print(f"Skipped stages: {result.skipped_stages}")
    print(f"Warnings: {result.warnings}")
    print(f"Errors: {result.errors}")


if __name__ == "__main__":
    main()