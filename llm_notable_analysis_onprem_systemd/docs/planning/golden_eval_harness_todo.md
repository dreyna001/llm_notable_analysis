# Golden Evaluation Harness TODO

## Status

**Partial.** First analyzer disposition slice is implemented (see
[`../testing/GOLDEN_EVAL.md`](../testing/GOLDEN_EVAL.md)): three baseline alerts,
offline rubric tests, and opt-in live eval. Broader harness items below remain
backlog (portal chat evals, timer automation, drift export, full corpus).

Complements shipped unit/smoke tests documented in
[`../testing/TESTING.md`](../testing/TESTING.md) and the planned integrity/drift
layer in
[`ai_integrity_drift_monitoring_plan.md`](ai_integrity_drift_monitoring_plan.md).

## Related docs

| Topic | Doc |
|-------|-----|
| Current test baseline | [`../testing/TESTING.md`](../testing/TESTING.md) |
| Integrity / drift monitoring (planned) | [`ai_integrity_drift_monitoring_plan.md`](ai_integrity_drift_monitoring_plan.md) |
| Portal Case Q&A contract | [`../technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md) |
| Prompt / measurement backlog | [`FUTURE_ENHANCEMENTS_ROADMAP.md`](FUTURE_ENHANCEMENTS_ROADMAP.md#spl-and-elasticsearch-grounding-quality-program) |
| Manual preview chat questions | [`../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md) |
| Preview scenario fixtures (cases 1-5) | [`../../data/preview_scenarios/README.md`](../../data/preview_scenarios/README.md) |

## Goal

Add an automated evaluation harness that runs on a regular cadence (for example
weekly) against a configured analyzer service and the shipped read-only portal
Case Q&A (Notable Archive Assistant) to detect **quality regressions** that
unit tests and smoke tests do not catch.

Existing tests prove contracts, validators, retrieval plumbing, policy gates,
portal API shape, and service health. This harness should evaluate whether live
(or staged-lab) analysis and assistant answers stay grounded, useful, and stable
against a representative set of known cases with explicit rubrics.

Long term, every feature surface that can be meaningfully evaluated should get
golden coverage, with separate fixtures and rubrics added as each capability
stabilizes.

## Baseline coverage today

What exists now (see [`../testing/TESTING.md`](../testing/TESTING.md)):

| Layer | What it proves | What it does **not** prove |
|-------|----------------|----------------------------|
| **Unit tests** (`pytest llm_notable_analysis_onprem_systemd/tests/...`) | Analyzer JSON schema, content-policy, SPL-query, and competing-hypothesis validators; mocked LLM integration branches; RAG Postgres ingest/retrieval SQL; portal OpenAPI/API contracts; case chat weak-retrieval, refusal, and citation paths with fakes; deployment/installer contracts | End-to-end output quality against a fixed corpus; cross-run stability; live-model grounding |
| **`smoke_postgres_rag.sh`** | Real Postgres/pgvector ingest and both `SOC_OPERATIONAL_CONTEXT` and `SPL_QUERY_GROUNDING_CONTEXT` retrieval paths | Mixedbread embeddings, reranking, or LLM synthesis quality |
| **`smoke_service_chain.sh`** | vLLM, LiteLLM, and analyzer health; optional file-drop path | Analysis correctness or regression scoring |
| **Preview scenarios (cases 1-5)** | Stored analyzer bundles for UI demo; manual chat investigation guide | Automated pass/fail rubrics or machine-readable eval reports |

Documented expectation on Linux validation hosts: ~432 passed for
`tests/onprem_service`; ~485 passed for the full on-prem package suite (see
[`../testing/TESTING.md`](../testing/TESTING.md)).

**Harness gap:** fixed golden inputs, expected-outcome rubrics, hallucination and
grounding checks over real/staged LLM outputs, and a stable eval report suitable
for release review.

## TODO

### Analyzer golden set

- Build a representative notable corpus with expected outcomes and rubrics.
- Include true positives, false positives, benign administrative activity,
  noisy low-confidence alerts, weak-signal alerts, malformed or sparse inputs,
  and cases where the correct answer is `unknown` or no-match.
- Pair each notable with expected source evidence, expected advisory KB/SOP
  references, and acceptable answer properties.
- Add hallucination scoring: unsupported facts, missing sources, treating SOP
  guidance as case evidence, or failing to use `unknown` when facts are absent.
- Add bad-analysis regression checks: verdict drift, missing direct evidence,
  unsupported ATT&CK mappings, unsafe recommendations, and failure to separate
  evidence from inference.
- Add weak-retrieval and no-match quality evaluation for RAG and SPL query
  grounding.

Seed candidates (not a harness today): preview alerts/bundles under
[`../../data/preview_scenarios/`](../../data/preview_scenarios/) and manual
question lists in
[`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md).

### Portal Case Q&A evals

Portal and Case Q&A are **shipped**; harness coverage is not.

- Selected-case questions over the current alert plus stored analysis.
- Global questions over the retained 30-day case archive (when enabled).
- Mixed questions separating current alert facts, prior case facts, and SOC
  advisory guidance.
- No-match and weak-retrieval questions that should return `unknown`.
- Action-request questions that must be refused (portal is read-only).

Representative assistant questions to cover:

- "What was the last notable about, and how should we handle it per our SOPs?"
- "Have we seen this host, user, IOC, or search name in the last 90 days?"
- "What recent notables look related to this one?"
- "Summarize this week's high-confidence alerts with source links."
- "Which weekly patterns should an analyst review?"

### Future surfaces (not shipped)

- **Weekly summary generation** — no weekly-summary feature exists in
  `onprem_service` yet; add eval cases only after that surface is defined and
  implemented.
- When implemented, check that summaries cite retained cases, avoid unsupported
  trend claims, and separate case facts from advisory customer guidance.

## Proposed automation shape

- Run as an explicit operator command first, then optionally as a weekly
  systemd timer such as `notable-eval.timer` after the corpus and thresholds are
  approved.
- Execute in a lab, staging, or approved evaluation profile by default. Do not
  make production analysis dependent on eval availability.
- Use fixed eval inputs and fixed KB/SPL source docs so regressions are
  attributable to prompt, model, retrieval, validator, or report-rendering
  changes.
- Record prompt version, model id, capability profile, retrieval source ids,
  citations, validation failures, latency, and pass/fail scores.
- For portal Case Q&A evals, also record selected case id, retrieved case ids,
  source lanes used (`current_alert`, `case_analysis`, `knowledge_base`,
  `prior_case`), citation coverage, and refusal/no-match reasons.
- Store eval outputs under an operator-controlled artifact directory, not in the
  normal case archive unless an explicit audit/evaluation capability enables it.
- Fail closed for malformed eval fixtures and invalid expected-output rubrics.

## Acceptance criteria for first slice

- A small golden set exists with at least one true positive, one false positive,
  one benign/admin case, one weak-retrieval case, and one no-match case.
- The harness runs end to end from one command against a configured analyzer
  service or approved local/staged test profile.
- The harness reports pass/fail for:
  - schema validity
  - source citation coverage
  - hallucination/unsupported-claim checks
  - evidence-vs-inference separation
  - RAG/SPL advisory-context separation
  - expected `unknown` / no-match behavior
- The harness produces a stable machine-readable report and a short human
  summary suitable for release review.

## Non-goals

- Do not call live Splunk, ServiceNow, SOAR, or other external systems from the
  eval harness unless a separate integration evaluation profile explicitly
  allows it.
- Do not use production-sensitive customer payloads in the shared golden set.
- Do not treat LLM self-grading as the only quality gate; deterministic checks
  and explicit rubrics remain required.
- Do not make this a replacement for analyst acceptance testing or manual preview
  walkthroughs.

## Open decisions

- Golden-set storage location and redaction standard.
- Whether the first version runs against the live service, a local mocked
  service, or both.
- Score thresholds for blocking release vs warning only.
- Who owns ongoing true-positive/false-positive corpus curation.
- How eval results tie back to prompt versions, KB versions, and model changes.
- Whether preview scenarios 1-5 become canonical golden cases or only informal
  seeds.
