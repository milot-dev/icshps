# ICSHPS

**Intelligent Candidate Screening & Hiring Pipeline System**

ICSHPS is a local deterministic AI hiring workflow prototype designed to process structured Hiring Bundles and produce audit friendly candidate screening artifacts for human review.

The project focuses on controlled agent style processing, traceable evidence, shared schema contracts, deterministic run outputs, and a simple local demo flow. It is not a production ATS, background checking platform, or autonomous hiring decision maker.

---

## Current Project State

The project is currently a local deterministic MVP backend with expanded
multi-candidate, triage, verification, and single-PDF demo support.

The repository includes:

- Hiring Bundle structure
- `manifest.yaml` input contract
- shared Pydantic schema models
- deterministic run scaffolding
- Hiring Bundle loader and validation
- Application Intake / Context Agent
- deterministic end-to-end backend workflow
- clean-PDF resume text extraction baseline
- candidate profile extraction baseline
- multi-candidate pipeline handling
- synthetic profile fallback
- JD matching baseline
- EEO compliance checks baseline
- mandatory certification checks baseline
- credential and LinkedIn consistency verification checks
- exception triage and lead orchestration logic
- structured findings format
- final routing decisions
- shortlist, hiring packet, audit log, and metrics artifacts
- one-command Hiring Bundle and single-PDF demo runs
- scenario validation for MVP test bundles
- unit tests for the implemented foundation and backend pipeline

---

## Current Workflow

The current MVP backend workflow executes a deterministic end-to-end hiring pipeline:

```text
Hiring Bundle or Single Clean PDF Resume
   ↓
Run Scaffolding
   ↓
Bundle Loader and Manifest Validation
   ↓
Application Intake / Context Agent
   ↓
Resume Extraction Agent
   ↓
JD Matching Agent
   ↓
Credential Consistency Verification Agent
   ↓
EEO Compliance Agent
   ↓
Anomaly Detection Agent
   ↓
Exception Triage and Lead Orchestration Agent
   ↓
Final Routing Decisions and Run Artifacts
```

The backend pipeline deterministic. Each run creates a dedicated run directory under `runs/`, allowing the same input bundle to be re run and inspected consistently.

Current generated outputs include:

```text
runs/<run_id>/
  run_metadata.json
  artifact_manifest.json
  inputs/
    context_packet.json
    manifest_snapshot.yaml
  artifacts/
    intake_findings.json
    candidate_profile.json
    match_scores.json
    compliance_flags.md
    verification_findings.json
    anomaly_findings.json
    final_decision.json
    shortlist.csv
    hiring_packet.json
    metrics.json
    audit_log.md
  logs/
    audit_events.jsonl
```

The pipeline currently runs through scaffolding, bundle loading, validation, intake, extraction, matching, verification, compliance checks, anomaly detection, exception triage, routing, and final artifact generation.

All final routing recommendations are decision support outputs and require human approval.

---

## Running the Project

Install dependencies:

```bash
uv sync
```

Run the test suite:

```bash
uv run pytest
```

Run the backend pipeline for a Hiring Bundle:

```bash
uv run python scripts/run_pipeline.py data/hiring_bundles/clean_standard_application --runs-root runs --reset
```

Run the backend pipeline for a single clean PDF resume:

```bash
uv run python scripts/run_pipeline.py data/hiring_bundles/clean_standard_application/resumes/candidate_clean_001_resume.pdf --runs-root runs --reset
```

Run scenario validation for all available MVP Hiring Bundles:

```bash
uv run python scripts/validate_scenario_bundles.py --allow-missing-scenarios
```

Run the Streamlit demo shell:

```bash
uv run streamlit run streamlit_app.py
```

Check linting with Ruff:

```bash
uv run ruff check .
```

The current pipeline writes run outputs to:

```text
runs/<run_id>/
```

---

## Project Goal

The goal of ICSHPS is to demonstrate how a controlled multi-agent hiring workflow can process candidate applications, extract structured candidate information, match candidates against job requirements, flag compliance and credential issues, detect application anomalies, route exceptions, and produce transparent artifacts for human review.

ICSHPS is not a production ATS, background-checking system, HRIS platform, or autonomous hiring decision maker. It is a local deterministic MVP that demonstrates traceable, audit-friendly candidate screening and routing.
