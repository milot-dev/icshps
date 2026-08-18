# Integration Contracts

These contracts are frozen for Sprint 2. Do not rename artifact files, routing labels, or shared schemas without team approval.

## Frozen Run Artifacts

| Artifact | Owner | Contract |
|---|---|---|
| `context_packet.json` | Member 1 | `BundleContext` |
| `intake_findings.json` | Member 1 | `FindingsArtifact` |
| `candidate_profile.json` | Member 2 | `CandidateProfile` |
| `candidate_profiles.json` | Member 2 | `list[CandidateProfile]` |
| `match_scores.json` | Member 2 | `MatchResultsArtifact` |
| `compliance_flags.md` | Member 3 | Markdown |
| `verification_findings.json` | Member 3 | `FindingsArtifact` |
| `anomaly_findings.json` | Member 3 | `FindingsArtifact` |
| `final_decision.json` | Member 1 | `FinalDecisionArtifact` |
| `shortlist.csv` | Member 1 | CSV |
| `hiring_packet.json` | Member 1 | JSON |
| `metrics.json` | Member 1 | JSON |
| `audit_log.md` | Member 1 | Markdown |

## Frozen Routing Categories

Use only `RoutingCategory` from `src/icshps/schemas/common.py`.

Do not add duplicate labels such as:

- `Manual credential review`
- `Pending credential verification`
- `Employment history inconsistency — manual review`

Use the existing canonical labels and put extra detail in the `reason` field.

## Frozen Findings Contract

All structured findings must use:

```python
FindingsArtifact
```

This applies to:

- intake findings
- compliance findings
- credential findings
- LinkedIn/mock profile consistency findings
- anomaly findings
- triage findings

Do not create another findings schema in Sprint 2.

## Frozen Final Decision Contract

Final routing output must use:

```python
FinalDecisionArtifact
```

All routing decisions must remain human-review recommendations, not autonomous hiring or rejection decisions.

## Sprint 2 Boundary

No Streamlit UI logic, real LinkedIn scraping, real background checks, real ATS integration, real HRIS posting, cloud deployment, RAG, or full MCP implementation should be added in this contract task.
