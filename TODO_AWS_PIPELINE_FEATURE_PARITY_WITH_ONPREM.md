# AWS notable pipeline — feature parity with on-prem

Status index for optional capabilities that exist (or are specified) for
`llm_notable_analysis_onprem_systemd/` relative to `s3_notable_pipeline/`
(S3 -> Lambda -> Bedrock -> sinks).

**Normative on-prem contract:**
[`llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md`](llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md)

**Architecture companion:**
[`llm_notable_analysis_onprem_systemd/docs/architecture/feature_enhancements_architecture.md`](llm_notable_analysis_onprem_systemd/docs/architecture/feature_enhancements_architecture.md)

---

## Wave 1 (analyzer parity) — complete

Wave 1 runtime implementation is **code-complete**. See
[`s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_PLAN.md`](s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_PLAN.md)
for the diff sequence, scope contract, and remaining closeout (real-AWS deploy
validation only; delivery docs refreshed).

Implemented in `s3_notable_pipeline/`:

- [x] **SPL query generation** — second bounded Bedrock call, contract validation, merge-by-position, repair-once behavior (`spl_query_generation.py`, tests).
- [x] **Read-only Splunk investigation** — REST oneshot and MCP-over-HTTPS executors with policy gates (`splunk_investigation.py`, tests).
- [x] **Splunk MCP executor** — `INVESTIGATION_QUERY_EXECUTOR=rest|mcp` parity option (configured runtime HTTP integration, no Cursor dependency).
- [x] **Query-result enrichment + markdown** — deterministic `query_result_section` and Query Results rendering (`query_result_enrichment.py`, `markdown_generator.py`, tests).
- [x] **ServiceNow incident draft and approval-gated create** — draft has no network side effect; create requires approval metadata (`servicenow.py`, tests).
- [x] **RAG / KB grounding** — Bedrock Knowledge Base retrieval for general SOC RAG, SPL grounding, and Elastic grounding (`bedrock_kb_retrieval.py`, grounding modules, operations docs).
- [x] **Cross-cutting Wave 1 requirements** — default-off capability profiles, fail-closed validation, orchestration order, deterministic mocked unit tests (`s3_notable_pipeline/tests/`), SAM/CFN contract sync (`config.env.example`, operations docs).

Wave 1 also shipped: Elasticsearch read-only investigation, query-result
interpretation, HTML reports, DynamoDB side-effect idempotency, and AWS
operations docs. Unit tests pass locally with mocked clients only; **real AWS
deploy validation is not recorded in this repo**.

---

## Wave 2 (portal, archive, Case Q&A) — complete

Case archive, analyst portal, and retrieval-bound Case Q&A were **explicitly out
of Wave 1**. They are specified in
[`s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`](s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md).

Wave 2 implementation (landed on `main`):

- [x] Diff 1: `analyst_portal` capability profile, config validation, and deploy scaffolding
- [x] Diff 2: Case archive write path and DynamoDB CaseIndex
- [x] Diff 2b: Post-archive embed Lambda and S3 case chunks
- [x] Diff 3: Read-only portal API Lambda and OpenAPI contract
- [x] Diff 4: Retrieval-bound pinned-case Q&A over retained cases
- [x] Diff 5: Read-only portal UI, auth, operations, and validation
- [x] IAM split between analyzer writer and portal reader permissions

---

## Future work (outside Wave 1 and Wave 2)

- [x] **Freeform / alternate entrypoints:** on-prem freeform analyzer removed; AWS stays batch-only on the structured analyzer path.
- [x] **Retention equivalence:** on-prem uses a systemd retention timer and
  filesystem/Postgres cleanup; AWS uses **S3 lifecycle** and **DynamoDB TTL**
  instead of porting `retention.py` literally. See
  [`s3_notable_pipeline/docs/operations/FILE_DROP_AND_RETENTION_OPERATIONS.md`](s3_notable_pipeline/docs/operations/FILE_DROP_AND_RETENTION_OPERATIONS.md).

---

## Wave 3 (runtime parity gaps) — open

Wave 1 and Wave 2 checklists are closed, but **on-prem and AWS behavior still
differ** in portal chat prompts, general-knowledge fallback, query-specific
retrieval, API contracts, and related areas.

**Current-state gap index (not a commitment backlog):**
[`AWS_ONPREM_RUNTIME_PARITY_GAPS.md`](AWS_ONPREM_RUNTIME_PARITY_GAPS.md)

**Portal chat Wave 3 (summary):**

- **Slice A — prompt/API parity:** Match on-prem prompts, API shape, guards, and
  Markdown answers (W3-1 through W3-8).
- **Slice B — hybrid retrieval:** AWS must implement Decision 7 (BM25 + Titan +
  RRF per question) to match on-prem case-chunk pick — **not** list-order S3
  load. Do **not** add rerank on case chunks; rerank stays KB-only (Decision 14).

**Post–Wave 3 (committed, not Wave 3):**

- **Multi-turn synthesis** on both platforms — ChatGPT-style follow-ups with
  prior turns in the model context. See
  [`PORTAL_CHATBOT_CAPABILITY_GAPS.md`](PORTAL_CHATBOT_CAPABILITY_GAPS.md) item 2
  and parity gaps doc **P3-1**.

**Not pursuing:** holistic / full-case inject; analyst-visible retrieval debug UI.

---

_Last updated: Wave 2 complete; Wave 3 gap index added; real-AWS deploy validation remains an operator step outside this repo._
