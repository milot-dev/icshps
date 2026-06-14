# ICSHPS

**Intelligent Candidate Screening & Hiring Pipeline System**

ICSHPS is a local deterministic AI hiring workflow prototype designed to process structured Hiring Bundles and produce audit-friendly candidate screening artifacts for human review.

The project focuses on controlled agent-style processing, traceable evidence, shared schema contracts, deterministic run outputs, and a simple local demo flow. It is not a production ATS, background-checking platform, or autonomous hiring decision-maker.

---

## Current Project State

The project is currently at the end of Sprint 1 foundations and early baseline agent implementation.

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
- synthetic profile fallback
- JD matching baseline
- EEO compliance checks baseline
- mandatory certification checks baseline
- structured findings format
- audit log and metrics initialization
- unit tests for the implemented foundation

The current workflow runs through intake and prepares the run directory for downstream agents. Downstream artifacts are reserved but not fully generated end-to-end yet.

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

Run the current Sprint 1 pipeline:

```bash
uv run python scripts/run_initial_workflow.py
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

At the current project state, the pipeline runs through run scaffolding, bundle loading, validation, and Application Intake / Context Agent. Downstream artifacts are reserved for Sprint 2 integration.

---

## Project Goal

The goal of ICSHPS is to demonstrate how a controlled multi-agent hiring workflow can process candidate applications, extract structured candidate information, match candidates against job requirements, flag compliance and credential issues, route exceptions, and produce transparent artifacts for human review.
