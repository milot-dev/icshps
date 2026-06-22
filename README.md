# ICSHPS

**Intelligent Candidate Screening & Hiring Pipeline System**


<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/uv-Package_Manager-4B32C3?style=for-the-badge" />
  <img src="https://img.shields.io/badge/Streamlit-Demo_UI-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white" />
  <img src="https://img.shields.io/badge/Pydantic-Schemas-E92063?style=for-the-badge&logo=pydantic&logoColor=white" />
  <img src="https://img.shields.io/badge/LangGraph-Orchestration-1C3C3C?style=for-the-badge" />
  <img src="https://img.shields.io/badge/PyMuPDF-PDF_Extraction-2E8B57?style=for-the-badge" />
  <img src="https://img.shields.io/badge/PyYAML-Bundle_Config-CB171E?style=for-the-badge" />
  <img src="https://img.shields.io/badge/pytest-Testing-0A9EDC?style=for-the-badge&logo=pytest&logoColor=white" />
  <img src="https://img.shields.io/badge/Ruff-Linting-D7FF64?style=for-the-badge" />
</p>


ICSHPS is a local deterministic AI hiring workflow prototype designed to process structured Hiring Bundles and produce audit friendly candidate screening artifacts for human review.

The project focuses on controlled agent style processing, traceable evidence, shared schema contracts, deterministic run outputs, and a simple local demo flow. It is not a production ATS, background checking platform, or autonomous hiring decision maker.

---


## Project State

The project is a local deterministic MVP backend with expanded
multi-candidate, triage, verification, single-PDF demo, and optional
LLM-assisted extraction recovery support.

The repository includes:

- Hiring Bundle structure
- `manifest.yaml` input contract
- shared Pydantic schema models
- deterministic run scaffolding
- Hiring Bundle loader and validation
- Application Intake / Context Agent
- deterministic LangGraph backend workflow
- clean-PDF resume text extraction baseline
- candidate profile extraction baseline
- multi-candidate pipeline handling
- persisted multi-profile extraction artifacts
- optional LangChain/OpenAI extraction recovery for weak deterministic parses
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
- LangGraph workflow tests
- unit tests for the implemented foundation and backend pipeline

---

## Workflow

The MVP backend workflow executes a deterministic end-to-end hiring pipeline:

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

Generated outputs include:

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
    candidate_profiles.json
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

The pipeline runs through scaffolding, bundle loading, validation, intake, extraction, matching, verification, compliance checks, anomaly detection, exception triage, routing, and final artifact generation.

`candidate_profile.json` remains the compatibility artifact for the primary candidate profile. `candidate_profiles.json` stores the full ordered list of extracted candidate profiles for multi-candidate runs.

The backend pipeline uses LangGraph orchestration by default. The optional `--engine langgraph` flag is accepted for explicit runs; the previous pure-Python engine is no longer supported.

All final routing recommendations are decision support outputs and require human approval.

Optional LLM extraction recovery is disabled by default. When enabled, deterministic extraction still runs first, and the LangChain/OpenAI helper is only used as a recovery path for low-confidence or incomplete resume extraction. LLM output is schema validated, evidence checked against resume text, rejected if it contains hiring or routing recommendation language, and falls back safely to deterministic extraction on provider, schema, or validation failure.

---

## Project Structure

```text
ICSHPS/
├── data/
│   ├── hiring_bundles/              # Scenario based Hiring Bundles used as pipeline inputs
│   └── sample_outputs/              # Example output artifacts
│
├── docs/                            # Project documentation and shared contracts
│
├── scripts/                         # Local CLI scripts for running and validating the pipeline
│   ├── run_pipeline.py              # Main one command backend pipeline runner
│   ├── validate_candidate_bundle.py # Single Hiring Bundle validation
│   └── validate_scenario_bundles.py # MVP scenario validation
│
├── src/
│   └── icshps/
│       ├── agents/                  # Agent and stage logic
│       ├── graph/                   # LangGraph workflow orchestration layer
│       │   ├── result.py            # Shared workflow result contract
│       │   ├── finalization.py      # Shared finalization helpers
│       │   ├── state.py             # LangGraph runtime state definition
│       │   └── langgraph_workflow.py # LangGraph runner and orchestration nodes
│       ├── policies/                # Reserved policy configuration package
│       ├── schemas/                 # Shared Pydantic schema contracts
│       ├── services/                # Bundle loading, artifact writing, run scaffolding
│       └── utils/                   # Small shared utility helpers
│
├── tests/                           # Unit and workflow tests
├── runs/                            # Generated run outputs
├── streamlit_app.py                 # Local Streamlit demo shell
├── pyproject.toml                   # Dependencies and project configuration
├── uv.lock                          # Locked dependency versions
└── README.md
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

Run the backend pipeline with an explicit LangGraph engine flag:

```bash
uv run python scripts/run_pipeline.py data/hiring_bundles/clean_standard_application --runs-root runs --reset --engine langgraph
```

Run the backend pipeline for a single clean PDF resume:

```bash
uv run python scripts/run_pipeline.py data/hiring_bundles/clean_standard_application/resumes/candidate_clean_001_resume.pdf --runs-root runs --reset
```

Run the LLM recovery demo bundle:

```bash
uv run python scripts/run_pipeline.py data/hiring_bundles/llm_recovery_skill_demo --runs-root runs --reset
```

Enable optional LLM recovery in a local `.env` or terminal environment:

```text
ICSHPS_LLM_EXTRACTION_ENABLED=true
OPENAI_API_KEY=your_key_here
ICSHPS_LLM_EXTRACTION_MODEL=gpt-4o-mini
ICSHPS_LLM_EXTRACTION_MAX_TOKENS=1200
```

Keep `ICSHPS_LLM_EXTRACTION_ENABLED=false` for deterministic-only runs, CI, offline development, or when no OpenAI quota is available. Do not commit local `.env` files.

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

The pipeline writes run outputs to:

```text
runs/<run_id>/
```

---

## Project Goal

The goal of ICSHPS is to demonstrate how a controlled multi-agent hiring workflow can process candidate applications, extract structured candidate information, match candidates against job requirements, flag compliance and credential issues, detect application anomalies, route exceptions, and produce transparent artifacts for human review.

ICSHPS is not a production ATS, background-checking system, HRIS platform, or autonomous hiring decision maker. It is a local deterministic MVP that demonstrates traceable, audit-friendly candidate screening and routing.
