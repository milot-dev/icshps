# Unified Findings Schema

Member 3 uses the existing `Finding` model in `src/icshps/schemas/findings.py` as the shared contract for compliance, credential, anomaly, matching, and routing signals.

## Required Contract

- `id`: stable finding identifier. This is the repo field for the project requirement named `finding_id`.
- `created_at`: deterministic audit timestamp. The MVP default is `1970-01-01T00:00:00Z` so repeated demo runs match exactly.
- `source_agent`: agent that produced the finding.
- `category`: one of `compliance`, `credential`, `anomaly`, `matching`, `triage`, or the other shared categories in `FindingCategory`.
- `severity`: `blocking`, `warning`, `info`, or `error`.
- `title`: short reviewer-facing title.
- `description`: full explanation.
- `reason`: concise rule reason used by reviewers and audit logs.
- `candidate_id` and `application_id`: optional join keys when the finding belongs to a candidate.
- `confidence`: deterministic score from `0.0` to `1.0`.
- `evidence`: one or more `EvidenceRef` objects with `source_path`, `source_type`, `section`, and `text_snippet`.
- `recommendation`: human-review routing guidance. This must not be treated as a final hiring decision.
- `requires_human_review`: `true` whenever human approval is needed.

## MVP Rule

Do not create another finding format for Member 3 agents. Compliance, mandatory certification, credential, LinkedIn consistency, anomaly, and triage work should all emit `FindingsArtifact`.
