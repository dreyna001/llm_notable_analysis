# Prompt And Analysis Enhancements Plan

## Status

Living planning document for prompt text and related analyzer/portal LLM paths.
Verified against `onprem_service/case_chat.py`, `local_llm_client.py`,
`local_llm_client_nonsdk.py`, `spl_query_generation.py`, `spl_query_grounding.py`,
`elastic_query_generation.py`, `elasticsearch_query_grounding.py`, and
`query_result_interpretation.py`.

| Item | Status | Notes |
|------|--------|-------|
| Portal chat prompts (`_build_prompt`, `_build_general_knowledge_prompt`) | **Shipped** | `case_chat.py` |
| Main alert analysis prompt (`LocalLLMClient._build_prompt`) | **Shipped** | Contract-first order; schema constraints in `OUTPUT_SCHEMA_RAW_JSON` |
| Structured repair template (`REPAIR_PROMPT_TEMPLATE_RAW_JSON`) | **Shipped** | Contract-aware per call type |
| SPL query generation prompt | **Shipped** | `spl_query_generation.py` |
| Elastic query generation prompt | **Shipped** | `elastic_query_generation.py` |
| Query-result interpretation + repair prompts | **Shipped** | `query_result_interpretation.py` |
| Freeform analyzer removal | **Shipped** | No `freeform_*` modules or systemd unit remain |
| SPL query RAG baseline (retrieval, context block, failure modes, token validation) | **Shipped** | `spl_query_grounding.py`; prompt rules in `SPL_QUERY_CONTEXT_RULES` |
| Elasticsearch grounding baseline | **Shipped** | `elasticsearch_query_grounding.py`; prompt rules in `ELASTIC_QUERY_CONTEXT_RULES` |
| Portal case-archive retrieval (chat RAG) | **Shipped** | Postgres chunk retrieval in `case_chat.py` |
| SPL/Elastic grounding quality program (tuning, eval, measurement) | **Planned** | Ops runbooks exist; golden harness not built |
| Bounded post-query reconciliation pass | **Planned** | Not in code; no `QUERY_RESULT_RECONCILIATION_*` config |

**Under review:** none.

This document does not change runtime contracts until corresponding code and tests
land.

## Goal

Improve analyst-facing LLM outputs without changing the read-only portal boundary
unless explicitly called out. Prompts should:

- keep case facts grounded in retrieved archive or alert input
- allow general cybersecurity knowledge for interpretation and next steps
- produce practical, scannable answers for trusted SOC analysts
- reduce model drift on structured JSON outputs
- keep query generation, execution, and interpretation in separate layers with
  clear provenance

## Platform note (investigation queries)

SPL prompt work here is **Splunk-only**. The analyzer selects one read-only
investigation backend via `INVESTIGATION_QUERY_BACKEND` (`splunk` or
`elasticsearch`). CrowdStrike, Security Onion, and a shared backend-agnostic
query prompt layer are **out of scope**.

---

## Shipped — portal chat (`case_chat.py`)

### `_build_general_knowledge_prompt`

**When:** Archive retrieval is empty or insufficient and
`CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`.

**Key instruction:** adaptive chatbot-style answer shape — answer directly,
stay concise by default, add structure only when helpful, and offer query
drafting only when it is the natural next step or explicitly requested.

### `_build_prompt`

**When:** Portal chat finds relevant archived case chunks.

**Key instruction:** retrieved archive is the only source of **case facts**;
general cyber/MITRE/IR knowledge may interpret facts and suggest validation;
answer naturally without forcing report sections; draft queries only when the
analyst explicitly asks, otherwise offer a short follow-up when a query is the
natural next step.

**Related:** portal archive retrieval uses Postgres chunk search in the same
module; SOC/SPL/Elastic KB lanes are optional advisory sources when configured.

---

## Shipped — main alert analysis (`local_llm_client.py`, `local_llm_client_nonsdk.py`)

### `LocalLLMClient._build_prompt`

**When:** First LLM call in the notable analyzer pipeline.

**Changes verified in code:**

1. **Contract-first order** — `TASK` then `OUTPUT CONTRACT:` with
   `{OUTPUT_SCHEMA_RAW_JSON}` before doctrine, evidence gate, and alert input.
   No duplicate schema block at the bottom.
2. **Strengthened schema constraints** in `OUTPUT_SCHEMA_RAW_JSON`:
   - mandatory contract; omit unsupported facts
   - direct evidence only from `SECURITY ALERT INPUT`
   - `SOC_OPERATIONAL_CONTEXT` may inform pivots but must not create findings,
     verdicts, IOCs, or TTP evidence
   - keep evidence, inference, and next steps separate

**Not in scope:** JSON schema, parsers, or validator shape changes.

### `REPAIR_PROMPT_TEMPLATE_RAW_JSON`

**When:** Single repair attempt after structured JSON parse/validation failure
(base analysis, SPL generation, Elastic generation).

**Verified rules:** repair structure only; no new facts; `"unknown"` / `[]`
fallbacks; include per-call `{contract}`; preserve valid prior fields; return one
JSON object only.

---

## Shipped — SPL query generation (`spl_query_generation.py`)

**When:** `INVESTIGATION_QUERY_BACKEND=splunk` and
`SPL_QUERY_GENERATION_ENABLED=true`.

**Verified prompt rules (`SPL_QUERY_GENERATION_RULES` + `SPL_QUERY_CONTEXT_RULES`):**

- draft-only SPL; do not claim execution or observed results
- one query per hypothesis; tie to hypothesis uncertainty and alert fields
- bounded time window when `ALERT_TIME` is set
- no invented indexes/sourcetypes/macros/CIM unless in alert or
  `SPL_QUERY_GROUNDING_CONTEXT`
- `SPL_QUERY_GROUNDING_CONTEXT` and `SOC_OPERATIONAL_CONTEXT` are advisory only

**Shipped validation:** `validate_spl_query_contract` rejects placeholders and,
when grounding context is present, ungrounded environment tokens; merges
`primary_spl_query_grounding_refs` deterministically.

---

## Shipped — Elasticsearch query generation (`elastic_query_generation.py`)

**When:** `INVESTIGATION_QUERY_BACKEND=elasticsearch` and
`ELASTIC_QUERY_GENERATION_ENABLED=true`.

**Verified prompt rules:** mirrors SPL generation-layer boundaries plus
Elastic-specific constraints — read-only `_search` Query DSL only; bounded
timestamp range; `bool.filter` / term / range patterns; no invented indexes or
fields; one index pattern per query; advisory `ELASTICSEARCH_GROUNDING_CONTEXT`.

**Shipped validation:** `validate_elastic_query_contract` and
`primary_elastic_query_grounding_refs` alignment in the same module.

---

## Shipped — query-result interpretation (`query_result_interpretation.py`)

**When:** After deterministic execution and `query_result_section` enrichment,
with `QUERY_RESULT_INTERPRETATION_ENABLED=true`.

**Verified rules:**

- zero results not automatically exculpatory
- `supports` / `weakens` rationale must cite `result_count` and
  `source_query_ref`
- `sample_rows` are bounded examples
- denied/failed/skipped queries -> `assessment="unknown"` unless another executed
  query supports the hypothesis
- scope limited to `query_result_interpretation`; must not mutate
  `alert_reconciliation` or other analysis fields
- backend-neutral opener (not Splunk-specific)

**Repair prompt:** scoped to interpretation JSON shape only; same no-new-facts
rules as general repair.

---

## Shipped — investigation query RAG baseline

Baseline retrieval plumbing and prompt injection are **implemented**. What
remains is operator curation and engineering follow-up for quality measurement
(see **Planned** below).

### SPL query RAG

**Modules:** `spl_query_grounding.py`, wired from `local_llm_client*.py`.

**Shipped:**

- `SPL_QUERY_RAG_ENABLED` Postgres provider (`spl_query_chunks` table)
- `build_spl_query_grounding_context` -> `SPL_QUERY_GROUNDING_CONTEXT` prompt block
- `SPL_QUERY_RAG_FAILURE_MODE`: `suppress` | `fallback_to_ungrounded`
- retrieval query from alert + hypotheses (`build_spl_query_grounding_query`)
- prompt labeling in `SPL_QUERY_CONTEXT_RULES`
- ungrounded token rejection and `primary_spl_query_grounding_refs`

**Ops:** [`KNOWLEDGE_BASE_OPERATIONS.md`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md),
[`SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md).

### Elasticsearch grounding

**Modules:** `elasticsearch_query_grounding.py`, wired from `local_llm_client*.py`.

**Shipped:** same pattern as SPL — dedicated Postgres table, context block,
`suppress` | `fallback_to_ungrounded`, prompt labeling, grounding refs,
field/index allowlist validation in `elastic_query_generation.py`.

**Ops:** [`KNOWLEDGE_BASE_OPERATIONS.md`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md),
[`ELASTICSEARCH_OPERATIONS.md`](../operations/investigation/ELASTICSEARCH_OPERATIONS.md).

Requires operator config for `ELASTICSEARCH_INDEX_ALLOWLIST`,
`ELASTICSEARCH_ALLOWED_FIELDS`, and `ELASTICSEARCH_TIMESTAMP_FIELD` before
generation or execution.

---

## Shipped — freeform analyzer removal

All freeform analyzer code and deployment artifacts removed. Runtime requires
structured SDK/client path and validated JSON contracts.

Verified absent: `freeform_llm_client.py`, `freeform_main*.py`,
`notable-analyzer-freeform.service` (see `test_deployment_contract.py`).

---

## Planned — grounding quality program

**Status:** Approved direction; baseline code shipped; tuning and measurement
not done.

Five-layer program (KB content, retrieval, prompt labeling, validation/failure
modes, measurement):

| Layer | Owner | Shipped baseline | Planned follow-up |
|-------|-------|------------------|-------------------|
| 1. KB content | Ops | Runbooks + ingest paths | Customer corpus curation |
| 2. Retrieval | Ops + engineering | Postgres hybrid retrieval, budgets, rerank flags | Snippet selection tuning; retrieval query shaping beyond alert + hypotheses |
| 3. Prompt labeling | Engineering | Advisory-context rules in SPL/Elastic modules | When to omit grounding blocks |
| 4. Validation | Engineering | Token/index rejection; failure modes; grounding refs | Expanded eval cases for grounded vs ungrounded emission |
| 5. Measurement | Ops + engineering | Unit/integration tests | Golden harness; representative notables ([`golden_eval_harness_todo.md`](golden_eval_harness_todo.md)) |

Shared retrieval knobs: `RAG_*`, `SPL_QUERY_RAG_*`, `ELASTICSEARCH_GROUNDING_*`.
Shared RAG package: `onprem_rag_notable_analysis`.

---

## Planned — bounded post-query reconciliation pass

**Status:** Not approved for implementation. Not in code.

**Distinct from query-result interpretation:** interpretation adds per-hypothesis
`supports` / `weakens` narrative and must not change `alert_reconciliation`.
Reconciliation would optionally align the **case-level verdict** with hunt
evidence after interpretation, preserving pre-query analysis for audit.

**Current pipeline (when execution + interpretation enabled):**

1. Main analysis LLM
2. SPL or Elastic query generation LLM
3. Deterministic query execution (up to 6 hypothesis queries)
4. Deterministic `query_result_section` enrichment
5. Optional `query_result_interpretation` LLM

Query results are added alongside the original analysis; they do **not** update
`alert_reconciliation.verdict`, TTP scores, or `evidence_vs_inference`.

**Recommended direction:** optional final step after 4–5; cite
`search_reference` / result counts; prefer `unknown` when queries fail or are
inconclusive; preserve before/after; gate behind config such as
`QUERY_RESULT_RECONCILIATION_ENABLED`.

**Open design questions (resolve before approval):**

- rule-based thresholds before any optional LLM synthesis
- output shape: new `post_query_reconciliation` block vs in-place update with
  immutable original
- scope: verdict/summary only vs confidence, actions, TTP emphasis
- portal/archive must expose pre-hunt vs post-hunt assessment if verdict can change

**Out of scope until approved:** runtime config, capability profile flag, code
changes, markdown rendering.

See also [`FUTURE_ENHANCEMENTS_ROADMAP.md`](FUTURE_ENHANCEMENTS_ROADMAP.md).

---

## Related docs

- [Feature enhancements technical spec](../technical_specs/feature_enhancements_technical_spec.md)
- [Analyst portal chat security](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md)
- [Analyst portal case archive plan](ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md)
- [Golden evaluation harness TODO](golden_eval_harness_todo.md)
- [Future enhancements roadmap](FUTURE_ENHANCEMENTS_ROADMAP.md)
- [Knowledge base operations](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md)
- [RAG operations](../operations/rag/RAG_OPERATIONS.md)
- [SPL operations](../operations/investigation/SPL_OPERATIONS.md)
- [Elasticsearch operations](../operations/investigation/ELASTICSEARCH_OPERATIONS.md)
