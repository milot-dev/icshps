# ICSHPS

**Intelligent Candidate Screening & Hiring Pipeline System**

ICSHPS is a local deterministic AI hiring workflow prototype designed to process structured Hiring Bundles and produce audit-friendly candidate screening artifacts for human review.

The project focuses on controlled agent-style processing, traceable evidence, shared schema contracts, deterministic run outputs, and a simple local demo flow. It is not a production ATS, background-checking platform, or autonomous hiring decision-maker.

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
- initial workflow skeleton
- clean-PDF resume text extraction baseline
- candidate profile extraction baseline
- multi-candidate pipeline handling
- synthetic profile fallback
- JD matching baseline
- EEO compliance checks baseline
- mandatory certification checks baseline
- exception triage findings
- structured findings format
- audit log and metrics initialization
- one-command Hiring Bundle and single-PDF demo runs
- unit tests for the implemented foundation and backend pipeline

Interview scheduling and expanded HRIS payload mapping remain out of scope for
the current implementation pass.

---

## Current Workflow

The current Sprint 1 workflow executes this deterministic sequence:

```text
Hiring Bundle
   ↓
Run Scaffolding
   ↓
Bundle Loader and Validation
   ↓
Application Intake / Context Agent
   ↓
Reserved downstream artifacts for Sprint 2
```

Current generated outputs include:

```text
runs/<run_id>/
  run_metadata.json
  artifact_manifest.json
  inputs/context_packet.json
  inputs/manifest_snapshot.yaml
  artifacts/intake_findings.json
  artifacts/candidate_profile.json
  artifacts/match_scores.json
  artifacts/compliance_flags.md
  artifacts/verification_findings.json
  artifacts/anomaly_findings.json
  artifacts/final_decision.json
  artifacts/shortlist.csv
  artifacts/hiring_packet.json
  artifacts/metrics.json
  artifacts/audit_log.md
  logs/audit_events.jsonl
```

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

At the current project state, the pipeline runs through run scaffolding, bundle
loading, validation, intake, extraction, matching, verification, compliance,
anomaly detection, exception triage, routing, and final artifact generation.

---

## Project Goal

The goal of ICSHPS is to demonstrate how a controlled multi-agent hiring workflow can process candidate applications, extract structured candidate information, match candidates against job requirements, flag compliance and credential issues, route exceptions, and produce transparent artifacts for human review.
