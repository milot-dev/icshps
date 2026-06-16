from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import ValidationError

from icshps.graph.workflow import EndToEndWorkflowResult, run_end_to_end_workflow
from icshps.schemas import FinalDecisionArtifact, RoutingCategory
from icshps.services.bundle_loader import MANIFEST_FILENAME, load_hiring_bundle
from icshps.services.run_scaffolding import (
    build_deterministic_run_id,
    compute_bundle_fingerprint,
)

REQUIRED_RUN_ARTIFACTS: tuple[Path, ...] = (
    Path("artifact_manifest.json"),
    Path("inputs/context_packet.json"),
    Path("artifacts/candidate_profile.json"),
    Path("artifacts/match_scores.json"),
    Path("artifacts/final_decision.json"),
    Path("artifacts/shortlist.csv"),
    Path("artifacts/hiring_packet.json"),
    Path("artifacts/metrics.json"),
    Path("artifacts/audit_log.md"),
)

DETERMINISTIC_ARTIFACTS: tuple[Path, ...] = REQUIRED_RUN_ARTIFACTS

EXPECTED_SCENARIO_ROUTING: dict[str, RoutingCategory] = {
    "strong_match_all_must_haves": RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
    "strong_match": RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
    "missing_mandatory_certification": RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL,
    "same_candidate_three_roles": RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW,
    "duplicate_multi_role": RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW,
    "linkedin_date_contradiction": RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY,
    "employment_date_contradiction": RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY,
    "eeo_age_language": RoutingCategory.EEO_COMPLIANCE_REVIEW,
    "surge_processing_mode": RoutingCategory.SURGE_PROCESSING_MODE,
    "bulk_applications_viral_post": RoutingCategory.SURGE_PROCESSING_MODE,
    "international_degree_pending_verification": RoutingCategory.CREDENTIAL_VERIFICATION_PENDING,
    "international_degree_not_verified": RoutingCategory.CREDENTIAL_VERIFICATION_PENDING,
    "low_confidence_handwritten_certification": RoutingCategory.MANUAL_REVIEW,
    "low_confidence_credential": RoutingCategory.MANUAL_REVIEW,
    "clean_standard_application": RoutingCategory.FAST_TRACK_REVIEW,
}

EXPECTED_SCENARIO_TYPES: tuple[str, ...] = (
    "strong_match_all_must_haves",
    "missing_mandatory_certification",
    "same_candidate_three_roles",
    "linkedin_date_contradiction",
    "eeo_age_language",
    "surge_processing_mode",
    "international_degree_pending_verification",
    "low_confidence_handwritten_certification",
    "clean_standard_application",
)

ROUTING_ALIASES: dict[str, RoutingCategory] = {
    category.value: category for category in RoutingCategory
}
ROUTING_ALIASES.update(
    {
        # Validation-only aliases for scenario wording in project docs.
        # These do not add or change canonical RoutingCategory labels.
        "Pending credential verification": RoutingCategory.CREDENTIAL_VERIFICATION_PENDING,
        "Manual credential review": RoutingCategory.MANUAL_REVIEW,
        "Employment history inconsistency — manual review": RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY,
        "Auto-reject": RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL,
    }
)


class PipelineRunner(Protocol):
    def __call__(
        self,
        bundle_path: str | Path,
        *,
        runs_root: str | Path,
        run_id: str | None = None,
        reset: bool = True,
    ) -> EndToEndWorkflowResult: ...


@dataclass(frozen=True)
class ValidationIssue:
    """One readable validation problem found for a scenario bundle."""

    check: str
    message: str


@dataclass(frozen=True)
class ScenarioValidationResult:
    """Validation result for one Hiring Bundle scenario run."""

    bundle_name: str
    bundle_path: str
    run_id: str | None
    run_dir: str | None
    scenario_type: str | None
    expected_routing: str | None
    actual_routing: tuple[str, ...] = ()
    status: str = "failed"
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def passed(self) -> bool:
        return self.status == "passed" and not self.issues


@dataclass(frozen=True)
class ScenarioValidationReport:
    """Summary report for all discovered scenario bundle validations."""

    bundles_root: str
    runs_root: str
    results: tuple[ScenarioValidationResult, ...]
    missing_scenarios: tuple[str, ...] = ()

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.results if not result.passed)

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and not self.missing_scenarios


def discover_scenario_bundles(bundles_root: Path) -> tuple[Path, ...]:
    """Return bundle directories that contain a manifest.yaml file."""

    if not bundles_root.exists() or not bundles_root.is_dir():
        return ()

    return tuple(
        sorted(
            path
            for path in bundles_root.iterdir()
            if path.is_dir() and (path / MANIFEST_FILENAME).exists()
        )
    )


def validate_all_scenario_bundles(
    *,
    bundles_root: Path = Path("data/hiring_bundles"),
    runs_root: Path = Path("runs"),
    check_determinism: bool = True,
    allow_missing_scenarios: bool = False,
    pipeline_runner: PipelineRunner = run_end_to_end_workflow,
) -> ScenarioValidationReport:
    """Discover, run, validate, and summarize all available scenario bundles."""

    bundle_paths = discover_scenario_bundles(bundles_root)
    results = tuple(
        validate_scenario_bundle(
            bundle_path=bundle_path,
            runs_root=runs_root,
            check_determinism=check_determinism,
            pipeline_runner=pipeline_runner,
        )
        for bundle_path in bundle_paths
    )

    observed_scenarios = {
        result.scenario_type for result in results if result.scenario_type is not None
    }

    missing_scenarios = tuple(
        scenario
        for scenario in EXPECTED_SCENARIO_TYPES
        if scenario not in observed_scenarios
    )

    if allow_missing_scenarios:
        missing_scenarios = ()

    return ScenarioValidationReport(
        bundles_root=str(bundles_root),
        runs_root=str(runs_root),
        results=results,
        missing_scenarios=missing_scenarios,
    )


def validate_scenario_bundle(
    *,
    bundle_path: Path,
    runs_root: Path,
    check_determinism: bool = True,
    pipeline_runner: PipelineRunner = run_end_to_end_workflow,
) -> ScenarioValidationResult:
    """Run one bundle through the backend pipeline and validate its outputs."""

    issues: list[ValidationIssue] = []
    scenario_type = read_manifest_scenario_type(bundle_path)
    expected_routing = read_manifest_expected_routing(bundle_path)

    if not bundle_path.exists():
        return _failed_bundle_result(
            bundle_path=bundle_path,
            issue=ValidationIssue(
                "bundle_exists",
                f"Bundle path does not exist: {bundle_path}",
            ),
        )

    if not (bundle_path / MANIFEST_FILENAME).exists():
        return _failed_bundle_result(
            bundle_path=bundle_path,
            issue=ValidationIssue(
                "manifest_exists",
                f"Missing manifest.yaml: {bundle_path}",
            ),
        )

    run_id = _stable_run_id(bundle_path)
    run_dir = runs_root / run_id

    loaded_bundle = load_hiring_bundle(bundle_path, run_id=run_id)
    if not loaded_bundle.ok:
        issues.extend(
            ValidationIssue("manifest_valid", error)
            for error in loaded_bundle.errors
        )
        return ScenarioValidationResult(
            bundle_name=bundle_path.name,
            bundle_path=str(bundle_path),
            run_id=run_id,
            run_dir=str(run_dir),
            scenario_type=scenario_type,
            expected_routing=expected_routing,
            status="failed",
            issues=tuple(issues),
        )

    if loaded_bundle.context is not None:
        scenario_type = loaded_bundle.context.scenario.type
        expected_routing = (
            loaded_bundle.context.scenario.expected_routing or expected_routing
        )

    first_result = pipeline_runner(
        bundle_path=bundle_path,
        runs_root=runs_root,
        run_id=run_id,
        reset=True,
    )

    if not first_result.ok:
        issues.append(
            ValidationIssue(
                "pipeline_completed",
                f"Pipeline status was {first_result.status}; "
                f"errors: {list(first_result.errors)}",
            )
        )
        return ScenarioValidationResult(
            bundle_name=bundle_path.name,
            bundle_path=str(bundle_path),
            run_id=run_id,
            run_dir=str(run_dir),
            scenario_type=scenario_type,
            expected_routing=expected_routing,
            status="failed",
            issues=tuple(issues),
        )

    issues.extend(validate_required_artifacts(run_dir))

    final_decision_path = run_dir / "artifacts/final_decision.json"
    actual_routing: tuple[str, ...] = ()

    if final_decision_path.exists():
        routing_issues, actual_routing = validate_final_decision(
            final_decision_path=final_decision_path,
            expected_routing=expected_routing,
            scenario_type=scenario_type,
        )
        issues.extend(routing_issues)

    if check_determinism and not issues:
        issues.extend(
            validate_deterministic_rerun(
                bundle_path=bundle_path,
                runs_root=runs_root,
                run_id=run_id,
                pipeline_runner=pipeline_runner,
            )
        )

    return ScenarioValidationResult(
        bundle_name=bundle_path.name,
        bundle_path=str(bundle_path),
        run_id=run_id,
        run_dir=str(run_dir),
        scenario_type=scenario_type,
        expected_routing=expected_routing,
        actual_routing=actual_routing,
        status="passed" if not issues else "failed",
        issues=tuple(issues),
    )


def validate_required_artifacts(run_dir: Path) -> tuple[ValidationIssue, ...]:
    """Check that all Task 7 required run artifacts exist."""

    issues: list[ValidationIssue] = []

    if not run_dir.exists():
        issues.append(
            ValidationIssue(
                "run_dir_created",
                f"Run directory was not created: {run_dir}",
            )
        )
        return tuple(issues)

    for relative_path in REQUIRED_RUN_ARTIFACTS:
        artifact_path = run_dir / relative_path
        if not artifact_path.exists():
            issues.append(
                ValidationIssue(
                    "required_artifact_exists",
                    f"Missing required artifact: {relative_path.as_posix()}",
                )
            )

    return tuple(issues)


def validate_final_decision(
    *,
    final_decision_path: Path,
    expected_routing: str | None,
    scenario_type: str | None,
) -> tuple[tuple[ValidationIssue, ...], tuple[str, ...]]:
    """Validate routing category, expected behavior, and human approval flags."""

    issues: list[ValidationIssue] = []

    try:
        payload = json.loads(final_decision_path.read_text(encoding="utf-8"))
        final_decision = FinalDecisionArtifact.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, ValueError) as exc:
        return (
            (
                ValidationIssue(
                    "final_decision_valid",
                    f"Invalid final_decision.json: {exc}",
                ),
            ),
            (),
        )

    if not final_decision.decisions:
        issues.append(
            ValidationIssue(
                "routing_present",
                "final_decision.json has no candidate decisions.",
            )
        )

    actual_categories = tuple(
        decision.routing_category.value for decision in final_decision.decisions
    )

    if any(not decision.requires_human_approval for decision in final_decision.decisions):
        issues.append(
            ValidationIssue(
                "human_approval_required",
                "All final decisions must require human approval.",
            )
        )

    expected_category = resolve_expected_routing(expected_routing, scenario_type)

    if expected_routing and expected_category is None:
        issues.append(
            ValidationIssue(
                "expected_routing_known",
                f"Expected routing is not recognized by validation aliases: "
                f"{expected_routing}",
            )
        )

    if expected_category is not None and expected_category.value not in actual_categories:
        issues.append(
            ValidationIssue(
                "routing_matches_expected",
                f"Expected routing '{expected_category.value}', "
                f"got {list(actual_categories)}.",
            )
        )

    return tuple(issues), actual_categories


def validate_deterministic_rerun(
    *,
    bundle_path: Path,
    runs_root: Path,
    run_id: str,
    pipeline_runner: PipelineRunner = run_end_to_end_workflow,
) -> tuple[ValidationIssue, ...]:
    """Run the same bundle twice with the same run ID and compare artifact bytes."""

    run_dir = runs_root / run_id
    first_fingerprints = fingerprint_artifacts(run_dir, DETERMINISTIC_ARTIFACTS)

    second_result = pipeline_runner(
        bundle_path=bundle_path,
        runs_root=runs_root,
        run_id=run_id,
        reset=True,
    )

    if not second_result.ok:
        return (
            ValidationIssue(
                "deterministic_rerun_completed",
                f"Deterministic rerun failed with status {second_result.status}.",
            ),
        )

    second_fingerprints = fingerprint_artifacts(run_dir, DETERMINISTIC_ARTIFACTS)

    changed = tuple(
        str(path)
        for path, first_digest in first_fingerprints.items()
        if second_fingerprints.get(path) != first_digest
    )

    if changed:
        return (
            ValidationIssue(
                "deterministic_outputs",
                f"Artifacts changed across identical rerun: {list(changed)}",
            ),
        )

    return ()


def fingerprint_artifacts(
    run_dir: Path,
    relative_paths: tuple[Path, ...],
) -> dict[Path, str]:
    """Create stable byte fingerprints for artifact comparison."""

    fingerprints: dict[Path, str] = {}

    for relative_path in relative_paths:
        path = run_dir / relative_path
        if path.exists():
            fingerprints[relative_path] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()

    return fingerprints


def resolve_expected_routing(
    expected_routing: str | None,
    scenario_type: str | None,
) -> RoutingCategory | None:
    """Resolve manifest or scenario expected routing to a canonical RoutingCategory."""

    if expected_routing:
        return ROUTING_ALIASES.get(expected_routing)

    if scenario_type:
        return EXPECTED_SCENARIO_ROUTING.get(scenario_type)

    return None


def read_manifest_scenario_type(bundle_path: Path) -> str | None:
    """Best-effort read of scenario.type without requiring full manifest validation."""

    raw = _read_raw_manifest(bundle_path)
    scenario = raw.get("scenario") if isinstance(raw, dict) else None

    if isinstance(scenario, dict):
        value = scenario.get("type")
        return str(value) if value is not None else None

    return None


def read_manifest_expected_routing(bundle_path: Path) -> str | None:
    """Best-effort read of scenario.expected_routing before contract validation."""

    raw = _read_raw_manifest(bundle_path)
    scenario = raw.get("scenario") if isinstance(raw, dict) else None

    if isinstance(scenario, dict):
        value = scenario.get("expected_routing")
        return str(value) if value is not None else None

    return None


def write_validation_report(
    report: ScenarioValidationReport,
    output_path: Path,
) -> Path:
    """Write a deterministic JSON validation report for team review."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_report_to_json(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def print_terminal_summary(report: ScenarioValidationReport) -> None:
    """Print a compact validation summary for local demo checks."""

    print("ICSHPS Scenario Validation")
    print()
    print(f"Passed: {report.passed_count}")
    print(f"Failed: {report.failed_count}")
    print(f"Missing scenarios: {len(report.missing_scenarios)}")
    print()

    print("Validated scenarios:")
    if not report.results:
        print("- none")

    for result in report.results:
        label = result.scenario_type or result.bundle_name
        print(f"- {label}: {result.status}")

    failures = [result for result in report.results if not result.passed]

    if failures or report.missing_scenarios:
        print()
        print("Failures:")

        for result in failures:
            label = result.scenario_type or result.bundle_name
            for issue in result.issues:
                print(f"- {label}: [{issue.check}] {issue.message}")

        for scenario in report.missing_scenarios:
            print(f"- missing scenario bundle: {scenario}")


def _stable_run_id(bundle_path: Path) -> str:
    fingerprint = compute_bundle_fingerprint(bundle_path)
    return build_deterministic_run_id(bundle_path.name, fingerprint)


def _failed_bundle_result(
    *,
    bundle_path: Path,
    issue: ValidationIssue,
) -> ScenarioValidationResult:
    return ScenarioValidationResult(
        bundle_name=bundle_path.name,
        bundle_path=str(bundle_path),
        run_id=None,
        run_dir=None,
        scenario_type=None,
        expected_routing=None,
        status="failed",
        issues=(issue,),
    )


def _read_raw_manifest(bundle_path: Path) -> dict[str, object]:
    path = bundle_path / MANIFEST_FILENAME

    if not path.exists():
        return {}

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}

    return raw if isinstance(raw, dict) else {}


def _report_to_json(report: ScenarioValidationReport) -> dict[str, object]:
    payload = asdict(report)
    payload["summary"] = {
        "passed": report.passed_count,
        "failed": report.failed_count,
        "missing_scenarios": len(report.missing_scenarios),
        "ok": report.ok,
    }
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate all available ICSHPS Hiring Bundle scenarios.",
    )
    parser.add_argument(
        "--bundles-root",
        type=Path,
        default=Path("data/hiring_bundles"),
        help="Directory containing scenario Hiring Bundles.",
    )
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Directory where validation run outputs are written.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("runs/scenario_validation_report.json"),
        help="JSON report path written after validation.",
    )
    parser.add_argument(
        "--skip-determinism",
        action="store_true",
        help="Skip repeated-run artifact comparison.",
    )
    parser.add_argument(
        "--allow-missing-scenarios",
        action="store_true",
        help="Do not fail when not all expected scenario bundles exist yet.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        report = validate_all_scenario_bundles(
            bundles_root=args.bundles_root,
            runs_root=args.runs_root,
            check_determinism=not args.skip_determinism,
            allow_missing_scenarios=args.allow_missing_scenarios,
        )
        write_validation_report(report, args.report_path)
        print_terminal_summary(report)
        print()
        print(f"Report: {args.report_path}")

        return 0 if report.ok else 1

    except KeyboardInterrupt:
        return 130

    except Exception as exc:
        print(f"ICSHPS scenario validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())