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

## Wave 2 (portal, archive, Case Q&A) — in progress

Case archive, analyst portal, and retrieval-bound Case Q&A were **explicitly out
of Wave 1**. They are specified in
[`s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md`](s3_notable_pipeline/docs/planning/AWS_ONPREM_PARITY_REQUIREMENTS_AND_DESIGN.md).

Open Wave 2 items (do not implement under Wave 1 closeout):

- [x] Diff 1: `analyst_portal` capability profile, config validation, and deploy scaffolding
- [x] Diff 2: Case archive write path and DynamoDB CaseIndex
- [x] Diff 2b: Post-archive embed Lambda and S3 case chunks
- [x] Diff 3: Read-only portal API Lambda and OpenAPI contract
- [x] Diff 4: Retrieval-bound pinned-case Q&A over retained cases
- [ ] Read-only portal API/UI
- [ ] IAM split between analyzer writer and portal reader permissions

---

## Future work (outside Wave 1 and Wave 2)

- [x] **Freeform / alternate entrypoints:** on-prem freeform analyzer removed; AWS stays batch-only on the structured analyzer path.
- [ ] **Retention equivalence:** on-prem uses systemd timers; AWS typically uses **S3 lifecycle**, optional EventBridge cleanup, or downstream ops — document equivalence rather than porting `retention.py` literally (`FILE_DROP_AND_RETENTION_OPERATIONS.md` is the starting point).

---

_Last updated: Wave 2 Diff 4 complete; portal frontend/ops validation starts in Diff 5._
