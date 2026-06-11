# Prompt And Analysis Enhancements Plan

## Status

Living planning document for prompt text improvements across the analyst portal
chat path and the notable analyzer LLM path, plus one related analyzer pipeline
enhancement for post-query reconciliation.

Items marked **Approved** are agreed for implementation; **Planned** items are
agreed direction but need a separate design/implementation block (including
post-query reconciliation). Others remain under review.

This document does not change runtime contracts until the corresponding code and
tests land.

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

SPL prompt work in this plan is **Splunk-only**. The analyzer already selects one
read-only investigation backend via `INVESTIGATION_QUERY_BACKEND` (`splunk` or
`elasticsearch`). CrowdStrike, Security Onion, and a shared backend-agnostic query
prompt layer are **out of scope** for this document.

## Approved Changes

The following items are **implemented** on branch `feature/prompt-enhancements` unless
noted otherwise. Post-query reconciliation remains **Planned** only.

### `_build_general_knowledge_prompt` — portal chat fallback

**Status:** Implemented.

**Module:** `onprem_service/case_chat.py`

**When used:** Archive retrieval is empty or insufficient and
`CASE_QA_GENERAL_KNOWLEDGE_ENABLED=true`.

**Change:** Add a flexible answer-shape instruction:

```text
Prefer clear, analyst-friendly structure. Use sections such as short answer,
assumptions, reasoning, recommended steps, draft queries or examples, validation
checks, caveats, and next questions when they help. Do not force every section
into every answer.
```

**Why:** Improves consistency across cyber, IT, cloud, coding, and troubleshooting
questions without rigid templates.

---

### `_build_prompt` — case-grounded portal chat

**Status:** Implemented.

**Module:** `onprem_service/case_chat.py`

**When used:** Portal chat finds relevant archived case chunks for the analyst
question.

**Change:** Replace overly strict “answer only from archive” wording with:

```text
Use the retrieved archive context as the only source of case facts. You may use
general cybersecurity knowledge, adversary tradecraft, MITRE ATT&CK, detection
engineering, and incident response expertise to interpret those facts and suggest
validation steps. Clearly separate case-supported facts from inference, general
guidance, and draft queries.
```

Optional answer shape when useful:

```text
- Grounded answer: facts supported by retrieved archive context
- Unknowns: what the archive does not establish
- Suggested next steps: analyst actions or pivots
- Draft query/example: unvalidated draft text for human review
```

**Why:** Analysts need model expertise on top of case evidence; the portal must
not blur generated guidance with retained case facts.

---

### `LocalLLMClient._build_prompt` — main alert analysis prompt

**Status:** Implemented.

**Modules:** `onprem_service/local_llm_client.py`,
`onprem_service/local_llm_client_nonsdk.py`

**When used:** First LLM call in the notable analyzer pipeline (structured JSON
analysis of a single alert).

**Change 1 — contract-first prompt order:** Move the output contract earlier in
the prompt, after a short task statement:

```text
You are a cybersecurity expert producing a structured SOC analysis from a single alert.

TASK:
Analyze one alert only. Produce a verdict, separate direct evidence from inference,
extract supported IOCs, map MITRE ATT&CK only when direct evidence supports it,
and generate competing benign/adversary hypotheses for analyst validation.

OUTPUT CONTRACT:
{OUTPUT_SCHEMA_RAW_JSON}

---
(doctrine, evidence gate, scoring, hypotheses, procedure, alert input, SOC context, rules)
```

Remove the duplicate `{OUTPUT_SCHEMA_RAW_JSON}` block from the bottom of the
prompt after the reorder.

**Change 2 — strengthen `OUTPUT_SCHEMA_RAW_JSON` constraints:**

```text
- This contract is mandatory; omit unsupported facts rather than inventing values.
- Direct alert evidence must come only from SECURITY ALERT INPUT.
- SOC_OPERATIONAL_CONTEXT may inform analyst pivots and recommended validation
  steps, but it must not create findings, verdicts, IOCs, or TTP evidence by itself.
- Keep direct evidence, inference, and recommended next steps separate.
```

**Why in simple terms:**

- `OUTPUT_SCHEMA_RAW_JSON` is the detailed rulebook for required JSON output.
- `OUTPUT CONTRACT:` is a prompt heading that puts that rulebook upfront so the
  model knows the destination before reading doctrine and evidence rules.

**Not in scope for this item:** changing the JSON schema, parsers, or validators.

---

### `build_spl_query_generation_prompt` — Splunk query generation (second LLM call)

**Status:** Implemented.

**Module:** `onprem_service/spl_query_generation.py`

**When used:** After main alert analysis, when `INVESTIGATION_QUERY_BACKEND=splunk`
and `SPL_QUERY_GENERATION_ENABLED=true`. Produces draft SPL per competing
hypothesis. Execution and interpretation are separate downstream steps.

**Change 1 — generation layer is draft-only:**

```text
Generated SPL is unvalidated draft investigation guidance. Do not claim the query
was executed or that results were observed.
```

This keeps output valid whether or not `INVESTIGATION_QUERY_EXECUTION_ENABLED` is
on. When execution is enabled, deterministic results and interpretation carry
actual findings; generation must not pre-judge them.

**Change 2 — bounded time window when `ALERT_TIME` is provided:**

```text
When ALERT_TIME is provided, include an explicit bounded time window around it
using earliest/latest or an equivalent SPL time constraint.
```

**Change 3 — no invented Splunk environment tokens:**

```text
If no index, sourcetype, macro, or CIM data model is available in SECURITY ALERT
INPUT or SPL_QUERY_GROUNDING_CONTEXT, write the query without invented environment
tokens and focus on observable fields from the alert.
```

**Change 4 — tie each query to hypothesis and alert evidence:**

```text
Each query must name the hypothesis uncertainty it is testing and use exact alert
fields or values where available.
```

**Why:** Safer, more operational SPL that works with or without execution, and
aligns with the generation-only layer boundary.

**Deferred — SPL query RAG (follow-up block):**

**Status:** Approved direction (planning + ops runbook; engineering not implemented).

Ops onboarding, KB templates, quality checks, and retrieval tuning:
[`KNOWLEDGE_BASE_OPERATIONS.md`](../operations/KNOWLEDGE_BASE_OPERATIONS.md),
[`SPL_OPERATIONS.md`](../operations/SPL_OPERATIONS.md).

The prompt already accepts `SPL_QUERY_GROUNDING_CONTEXT` from
`SPL_QUERY_RAG_*` config. Improve quality in five layers:

| Layer | Owner | Focus |
|-------|-------|--------|
| 1. KB content | Ops | Curate indexes, sourcetypes, macros, field hints, examples |
| 2. Retrieval | Ops + engineering | Snippet selection, budgets, rerank (`SPL_QUERY_RAG_*`, shared `RAG_*`) |
| 3. Prompt labeling | Engineering | Grounding is advisory env context only, not alert evidence |
| 4. Validation + failure modes | Engineering | Ungrounded token rejection; `suppress` vs `fallback_to_ungrounded` |
| 5. Measurement | Ops + engineering | Representative notables, golden cases, post-ingest checklist |

Engineering follow-up topics (layers 2–5 code/prompt work):

- when to include vs omit SPL grounding in the prompt
- retrieval query shaping beyond alert + hypotheses text
- clearer labeling of grounding as advisory Splunk-environment context only
- eval cases for grounded vs ungrounded token emission
- alignment with `primary_spl_query_grounding_refs` validation

---

### `build_elastic_query_generation_prompt` — Elasticsearch query generation (second LLM call)

**Status:** Implemented.

**Module:** `onprem_service/elastic_query_generation.py`

**When used:** After main alert analysis, when
`INVESTIGATION_QUERY_BACKEND=elasticsearch` and
`ELASTIC_QUERY_GENERATION_ENABLED=true`. Produces draft Elasticsearch `_search`
Query DSL per competing hypothesis. Execution and interpretation are separate
downstream steps.

**Mirror Splunk generation-layer rules:**

```text
Generated Elasticsearch Query DSL is unvalidated draft investigation guidance.
Do not claim the query was executed or that results were observed.
```

```text
Each query must name the hypothesis uncertainty it is testing and use exact alert
fields or values where available.
```

**Elastic-specific prompt additions:**

```text
Use only read-only Elasticsearch _search Query DSL. Do not generate KQL, Lucene,
ES|QL, SQL, Kibana API calls, or prose queries.
```

```text
When ALERT_TIME is provided, build a bounded range filter around it on the
configured timestamp field. Otherwise stay within ELASTICSEARCH_MAX_TIME_RANGE.
```

```text
Prefer bool.filter, must_not, term, terms, exists, and range clauses for
evidence filtering. Avoid relevance-scoring patterns; security hunts should be
decision filters, not text-ranking searches.
```

```text
Do not invent index patterns, ECS/vendor dotted fields, or timestamp fields.
Use only fields and indexes from SECURITY ALERT INPUT or
ELASTICSEARCH_GROUNDING_CONTEXT.
```

```text
Use one index or index pattern per query, respect wildcard policy, and do not
emit comma-separated multi-index strings.
```

**Why:** Keeps Elastic output aligned with current validators and config
(`ELASTICSEARCH_INDEX_ALLOWLIST`, `ELASTICSEARCH_ALLOWED_FIELDS`,
`ELASTICSEARCH_TIMESTAMP_FIELD`, `ELASTICSEARCH_MAX_TIME_RANGE`) while preserving
the same generation-only boundary as SPL.

**Deferred — Elasticsearch grounding (follow-up block):**

**Status:** Approved direction (planning + ops runbook; engineering not implemented).

Ops onboarding and KB curation:
[`KNOWLEDGE_BASE_OPERATIONS.md`](../operations/KNOWLEDGE_BASE_OPERATIONS.md),
[`ELASTICSEARCH_OPERATIONS.md`](../operations/ELASTICSEARCH_OPERATIONS.md).

The prompt already accepts `ELASTICSEARCH_GROUNDING_CONTEXT` from
`ELASTICSEARCH_GROUNDING_*` config. Use the same five-layer quality program as
SPL (KB content, retrieval, prompt labeling, validation/failure modes,
measurement). Elastic additionally requires operator config for
`ELASTICSEARCH_INDEX_ALLOWLIST`, `ELASTICSEARCH_ALLOWED_FIELDS`, and
`ELASTICSEARCH_TIMESTAMP_FIELD` before generation or execution.

Engineering follow-up topics:

- snippet selection and retrieval query shaping
- allowed-field coverage vs grounding context
- failure modes and `primary_elastic_query_grounding_refs` validation
- eval cases for grounded vs ungrounded index patterns and fields

---

### `build_query_result_interpretation_prompt` — query result interpretation (post-execution LLM call)

**Status:** Implemented.

**Module:** `onprem_service/query_result_interpretation.py`

**When used:** After deterministic query execution and `query_result_section`
enrichment, when `QUERY_RESULT_INTERPRETATION_ENABLED=true`. Interprets executed
query facts per hypothesis; does not run queries or change deterministic result
fields.

**Change 1 — zero-result semantics:**

```text
A zero-result query is not automatically exculpatory. Interpret zero results
against the query intent, supports_if, weakens_if, query status, and known coverage.
```

**Change 2 — grounded supports/weakens rationale:**

```text
For assessment="supports" or "weakens", rationale must mention the relevant
result_count and at least one source_query_ref from QUERY_RESULT_INTERPRETATION_INPUT.
```

**Change 3 — sample rows are bounded examples:**

```text
Treat sample_rows as bounded examples from the executed query, not a complete
record of all matching telemetry.
```

**Change 4 — failed/denied/skipped queries:**

```text
If a query was denied, failed, skipped, or has no usable result_count, use
assessment="unknown" unless another executed query directly supports the same
hypothesis.
```

**Change 5 — explicit output scope (no forward references):**

```text
Scope for this step:
- Output only query_result_interpretation entries for each hypothesis.
- Do not output or modify alert_reconciliation, evidence_vs_inference,
  ioc_extraction, ttp_analysis, competing_hypotheses ordering, query status,
  result_count, or search_reference values.
- confidence_delta is a label for this interpretation only; it is not a numeric
  score update to any other field.
```

**Change 6 — backend-neutral wording:**

Replace “Splunk query execution results” with:

```text
You are interpreting deterministic read-only investigation query results for a
SOC notable.
```

**Why:** Keeps interpretation tied to executed query evidence, works for Splunk
or Elastic normalized results, and avoids ambiguous references to other pipeline
steps.

---

### `REPAIR_PROMPT_TEMPLATE_RAW_JSON` — structured output repair prompt

**Status:** Implemented (contract-aware repair with per-call schema).

**Modules:** `onprem_service/local_llm_client.py`,
`onprem_service/local_llm_client_nonsdk.py`

**When used:** Single repair attempt after a structured LLM call fails JSON
parsing or validation. Used by base analysis, SPL generation, and Elastic
generation paths.

**Change 1 — repair structure, not substance:**

```text
Repair only formatting, JSON validity, schema shape, enum values, and missing
required containers. Do not improve, expand, reinterpret, or add new analysis.
```

**Change 2 — forbid new facts:**

```text
Do not add facts, IOCs, hosts, users, timestamps, verdict reasons, TTPs, queries,
or result interpretations that were not present in the previous output or
original prompt context.
```

**Change 3 — define fallback values:**

```text
If a required field cannot be supported, use "unknown" for scalar fields and []
for list fields where the schema allows it.
```

**Change 4 — make repairs contract-aware:**

The repair prompt should include the relevant schema/contract for the failed
call: base analysis, SPL generation, Elastic generation, or query interpretation.

**Change 5 — preserve valid prior content:**

```text
Preserve valid fields from the previous output whenever they already satisfy the
contract. Only change fields needed to pass validation.
```

**Change 6 — keep strict output rule:**

```text
Return only one valid JSON object. No markdown fences, comments, prose, or
explanation.
```

**Why:** Repair should fix malformed structured output without becoming a second
analysis attempt or inventing cleaner but unsupported content.

---

### `build_query_result_interpretation_repair_prompt` — query interpretation repair prompt

**Status:** Implemented.

**Module:** `onprem_service/query_result_interpretation.py`

**When used:** Single repair attempt after the query-result interpretation LLM
response fails parsing or validation.

**Change:** Align this repair prompt with the general structured repair rules,
but scope it only to `query_result_interpretation`.

```text
Repair only the query_result_interpretation JSON shape, enum values, required
fields, and allowed source_query_refs. Do not reinterpret query results or add
new analysis.
```

```text
Use only QUERY_RESULT_INTERPRETATION_INPUT and the previous output. Do not add
new facts, result counts, search references, hypotheses, verdict changes, TTPs,
IOCs, users, hosts, timestamps, or telemetry claims.
```

```text
Preserve valid prior content whenever it already satisfies the contract. Only
change fields needed to pass validation.
```

```text
Return only one valid JSON object containing query_result_interpretation. No
markdown fences, comments, prose, or explanation.
```

**Why:** The repair call should fix malformed interpretation output without
becoming another chance to reason over or expand the executed query evidence.

---

### Freeform analyzer removal

**Status:** Implemented.

**Scope:** Remove all freeform analyzer code and deployment artifacts. The
runtime analyzer should require the structured SDK/client path and validated JSON
contracts.

Known files/artifacts to remove or replace references to:

- `src/llm_notable_analysis_onprem_systemd/onprem_service/freeform_llm_client.py`
- `src/llm_notable_analysis_onprem_systemd/onprem_service/freeform_main.py`
- `src/llm_notable_analysis_onprem_systemd/onprem_service/freeform_main_nonsdk.py`
- `deploy/systemd/notable-analyzer-freeform.service`
- any install, README, ops, tests, or docs references that expose freeform mode

**Why:** Freeform mode conflicts with the product direction: outputs are not
schema-validated, are harder for analysts to scan consistently, and bypass the
structured contracts used by the SDK/client analyzer path.

**Implementation note:** This is a code-removal block, not a prompt-tuning block.
Remove dead imports, systemd references, docs references, and any runtime
configuration paths in the same change.

## Planned Pipeline Enhancement

### Bounded post-query reconciliation pass

**Status:** **Planned** — keep in this document as future work. Not Approved for
implementation yet. Not prompt-only: needs orchestration, schema, validator, tests,
and a product decision on rule-based vs LLM reconciliation.

**Distinct from query-result interpretation:** Interpretation (step 5 below) adds
per-hypothesis `supports` / `weakens` narrative and must not change
`alert_reconciliation`. Reconciliation would optionally align the **case-level
verdict** with hunt evidence after interpretation, while preserving the
pre-query analysis for audit.

**Current behavior:** With execution and interpretation enabled, the pipeline is:

1. Main analysis LLM (verdict, hypotheses, TTPs from alert only)
2. SPL generation LLM
3. Deterministic query execution (up to 6 hypothesis queries)
4. Deterministic `query_result_section` enrichment
5. Optional `query_result_interpretation` LLM (supports/weakens per hypothesis)

Query results are **added alongside** the original analysis. They do **not**
currently update `alert_reconciliation.verdict`, TTP scores, or
`evidence_vs_inference`. Interpretation is explicitly forbidden from mutating
those fields today.

**Problem:** Analysts may see a verdict that ignores hunt results that were
actually run, which feels inconsistent even when the conservative design is
intentional.

**Recommended direction:** Add an **optional final reconciliation step** after
steps 4–5 above:

**Inputs:**

- original structured analysis (preserved for audit)
- deterministic `query_result_section`
- validated `query_result_interpretation` (when available)

**Output (new block or tightly scoped update):**

- revised verdict/summary only when query evidence clearly supports or weakens the
  prior assessment
- must cite `search_reference` and/or result counts
- if queries were denied, failed, skipped, or inconclusive, prefer `unknown` or
  leave verdict unchanged
- preserve pre-query analysis alongside post-query reconciliation (before/after)

**Design rules:**

- do not fold query results into the first analysis call (queries do not exist yet)
- do not silently overwrite the original analysis blob
- deterministic query facts first, LLM reconciliation second
- gate behind config (e.g. `QUERY_RESULT_RECONCILIATION_ENABLED`) and capability
  profile when implemented

**Why:** Gives analysts a final assessment that reflects hunts without letting
weak or zero-result queries freely rewrite the alert-only verdict.

**Open design questions (resolve before Approval):**

- **Rule-based first vs LLM second** — prefer deterministic thresholds (e.g.
  multiple `weakens` assessments with executed queries) before any optional LLM
  synthesis pass.
- **Output shape** — new `post_query_reconciliation` block with before/after
  verdict fields vs tightly scoped in-place update with immutable original copy.
- **Scope of change** — verdict and one-line summary only, or also confidence,
  `recommended_actions`, and TTP emphasis.
- **Zero-result semantics** — zero rows is not automatically exculpatory; align
  with interpretation prompt rules.
- **Portal and archive** — case chat and archived bundles must expose pre-hunt vs
  post-hunt assessment clearly if verdict can change.

**Out of scope until this item is Approved:** runtime config, capability profile
flag, code in `local_llm_client*.py`, markdown rendering changes.

## Under Review

Review these by function in follow-up sessions before approving:

| Function | Module | Topic |
|----------|--------|-------|
| (none) | — | SPL and Elastic grounding quality program moved to approved direction; see deferred blocks above and ops runbooks |

## Completed (code, not prompt text)

- Renamed Qwen-specific prompt helper names to generic structured-JSON hint
  names in `local_llm_client.py` and `local_llm_client_nonsdk.py`
  (`json_hint`, `_STRUCTURED_JSON_OUTPUT_HINT`, `_LLM_THINKING_TRACE_END`).
- All **Approved Changes** above (prompt text, repair templates, freeform removal).
- Ops runbooks for SPL/Elastic query KB onboarding in
  `KNOWLEDGE_BASE_OPERATIONS.md`, `SPL_OPERATIONS.md`, `ELASTICSEARCH_OPERATIONS.md`.

## Related Docs

- [Analyst portal chat security](../operations/ANALYST_PORTAL_CHAT_SECURITY.md)
- [Analyst portal case archive plan](ANALYST_PORTAL_CASE_ARCHIVE_PLAN.md)
- [Golden evaluation harness TODO](golden_eval_harness_todo.md)
