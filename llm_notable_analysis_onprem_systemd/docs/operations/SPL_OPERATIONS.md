# SPL Operations

This guide is for operators and Splunk owners who must tune Splunk-related
settings that almost always differ by customer: index inventory, acceptable
search commands, timeouts, concurrency, and how aggressively to enable
automatic query execution.

It complements the narrative in
[`EXECUTIVE_ONPREM_WORKFLOW.md`](../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
and the literal contract in [`config.env.example`](../../config.env.example).
Use those for end-to-end flow; use this doc when deciding safe values for your
environment.

## What This Controls

1. **SPL query generation (`SPL_QUERY_GENERATION_ENABLED`)**
   The analyzer asks the LLM for `primary_spl_query` strings per hypothesis.
   Nothing is executed unless you separately enable investigation execution.
   No Splunk credential is required for generation alone.

2. **Read-only investigation execution (`INVESTIGATION_QUERY_EXECUTION_ENABLED`)**
   The service may run generated SPL against Splunk using REST or an injected
   MCP client. This path uses Splunk credentials, applies deterministic policy
   locally, then submits the search. Policy is not a full Splunk SPL grammar
   check; malformed SPL may still be rejected by Splunk at runtime.

3. **Query-result interpretation (`QUERY_RESULT_INTERPRETATION_ENABLED`)**
   The service may run a third bounded LLM call after deterministic query
   execution to explain whether results support, weaken, or leave hypotheses
   inconclusive. This is disabled by default and does not change query status,
   result counts, search references, or existing confidence scores.

Tune each feature independently: many teams ship generation on long before
execution on.

## Recommended Starting Posture

- Start with `SPL_QUERY_GENERATION_ENABLED=true` and
  `INVESTIGATION_QUERY_EXECUTION_ENABLED=false`.
- Review generated SPL in reports with Splunk admins before allowing execution.
- Enable execution first in a lab or non-prod Splunk scope.
- Keep `QUERY_RESULT_INTERPRETATION_ENABLED=false` until deterministic query
  execution quality is accepted.
- Keep allowed indexes and commands narrow until denied/error rates are known.
- Use REST unless your environment requires an MCP broker or gateway.

## Customer Decisions

### SPL generation modes

SPL strings come from the same second LLM call whenever
`SPL_QUERY_GENERATION_ENABLED=true`. What changes per deployment is how much
retrieval context is attached to that prompt.

| Mode | Typical flags | Prompt context | Customer tuning |
|------|---------------|----------------|-----------------|
| Alert-only grounding | `SPL_QUERY_GENERATION_ENABLED=true`, `RAG_ENABLED=false`, `SPL_QUERY_RAG_ENABLED=false` | Raw alert plus hypotheses. `SOC_OPERATIONAL_CONTEXT` and `SPL_QUERY_GROUNDING_CONTEXT` are empty. | Expect SPL to lean only on observable fields from the notable. Generated queries may not assume customer indexes, sourcetypes, macros, or CIM datamodels. |
| General SOC KB RAG | `SPL_QUERY_GENERATION_ENABLED=true`, `RAG_ENABLED=true`, `SPL_QUERY_RAG_ENABLED=false` | Raw alert, hypotheses, and `SOC_OPERATIONAL_CONTEXT` from the normal KB. | Use the normal KB for analyst process and runbooks. It does not authorize environment-specific SPL tokens for generated queries. |
| Dedicated SPL grounding RAG | `SPL_QUERY_GENERATION_ENABLED=true`, `SPL_QUERY_RAG_ENABLED=true` | Raw alert, hypotheses, optional `SOC_OPERATIONAL_CONTEXT`, and separate `SPL_QUERY_GROUNDING_CONTEXT` from the Splunk-focused KB. | Curate real indexes, sourcetypes, macros, datamodel notes, saved searches, fields, and examples. Generated SPL may use environment-specific tokens only when they appear in the alert or this SPL grounding context. |

Across all modes, optional investigation execution still uses the same
deterministic `SPLUNK_SEARCH_*` policy. RAG does not bypass allowlists.

### Should SPL generation use a dedicated SPL KB?

**Settings:** `SPL_QUERY_RAG_ENABLED`, `SPL_QUERY_RAG_SOURCE_DIR`,
`SPL_QUERY_RAG_INDEX_DIR`, `SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE`,
`SPL_QUERY_RAG_MAX_SNIPPETS`, `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS`,
`SPL_QUERY_RAG_FAILURE_MODE`

- Keep `SPL_QUERY_RAG_ENABLED=false` until Splunk owners approve a curated
  source set.
- Use the dedicated SPL KB for environment facts: real `index=...`,
  `sourcetype=...`, macro names, datamodel names, saved searches, field
  dictionaries, CIM notes, and known-good query examples.
- Keep this KB separate from broad SOC runbooks. The normal
  `SOC_OPERATIONAL_CONTEXT` can guide analyst reasoning, but only
  `SPL_QUERY_GROUNDING_CONTEXT` authorizes environment-specific SPL tokens.
- Start with `SPL_QUERY_RAG_FAILURE_MODE=suppress` so generated SPL is omitted
  if the SPL KB is unavailable. Use `fallback_to_ungrounded` only if operators
  accept alert-only SPL generation during SPL KB outages.
- Keep `SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE` separate from
  `RAG_POSTGRES_CHUNKS_TABLE`; the default is `spl_query_chunks`.

**Grounding provenance (structured vs narrative).** Validated responses can
include per-hypothesis **`primary_spl_query_grounding_refs`** in the structured
LLM result; the shipped markdown report does **not** render those refs today.
Analysis **`metadata`** already records high-level SPL RAG posture
(`spl_query_rag_*`). If operators later want full provenance in **logs or
metadata** without expanding the markdown comment, see the **Future (optional):
observability without markdown bloat** note in
[`../architecture/feature_enhancements_architecture.md`](../architecture/feature_enhancements_architecture.md)
(§ SPL RAG grounding).

### Which indexes are in scope?

**Setting:** `SPLUNK_SEARCH_ALLOWED_INDEXES`

- Start from the smallest set needed for hypothesis validation.
- Align the list with Splunk RBAC for the service account or MCP broker.
- Prefer explicit `index=...` clauses in prompts and KB examples.
- Avoid broad catch-alls unless the Splunk owner has accepted the load and
  exposure tradeoff.

### How strict should command policy be?

**Settings:** `SPLUNK_SEARCH_ALLOWED_COMMANDS`,
`SPLUNK_SEARCH_DENIED_COMMANDS`

- Treat the shipped denied commands as a baseline, not a complete enterprise
  policy.
- Keep mutating, exfiltration, script, and REST-like commands denied for
  read-only investigation.
- Add more allowed commands only after seeing real generated SPL and reviewing
  it with Splunk admins.

### How much work may each search do?

**Settings:** `SPLUNK_SEARCH_MAX_TIME_RANGE`, `SPLUNK_SEARCH_MAX_ROWS`,
`SPLUNK_SEARCH_TIMEOUT_SECONDS`

- Match the time range to tier-1 triage norms first, then widen only with
  Splunk capacity sign-off.
- Keep row caps small enough for deterministic report enrichment.
- Set timeouts to avoid analyzer threads waiting on slow ad-hoc searches.

### How many searches may one notable trigger?

**Settings:** `INVESTIGATION_MAX_QUERIES_PER_ALERT`,
`INVESTIGATION_MAX_CONCURRENT_QUERIES`

- Lower concurrency first on smaller search heads.
- Keep query caps aligned with the number of hypotheses that actually carry
  executable SPL in your workflow.

### Should the LLM interpret query results?

**Settings:** `QUERY_RESULT_INTERPRETATION_ENABLED`,
`QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS`,
`QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS`,
`QUERY_RESULT_INTERPRETATION_MAX_TOKENS`

- Leave disabled for deterministic-only reports. The markdown still includes
  `Query Results` with status, result counts, sample columns, and search refs.
- Enable only when operators want an additional analyst narrative under
  `Query Result Interpretation`.
- The deterministic `Query Results` section is always preserved when
  interpretation is enabled.
- `confidence_delta` is model-generated prose guidance (`increase`, `decrease`,
  `unchanged`, `unknown`) and never changes `alert_reconciliation.confidence`,
  ATT&CK scores, query status, result counts, search refs, or hypothesis order.
- Keep `QUERY_RESULT_INTERPRETATION_MAX_TOKENS` smaller than the main analysis
  token cap; the interpretation schema is compact and should not reserve the
  full report-generation budget.
- If interpretation fails validation, the report keeps deterministic results and
  omits interpretation.

### REST or MCP?

**Setting:** `INVESTIGATION_QUERY_EXECUTOR=rest|mcp`

- **REST** fits direct analyzer-to-Splunk deployments.
- **MCP** fits environments where Splunk access is brokered outside the
  analyzer. The injected MCP client must implement `run_search(payload)`.
- Both modes run the same local policy gate before attempting execution.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Generation | `SPL_QUERY_GENERATION_ENABLED` |
| SPL grounding KB | `SPL_QUERY_RAG_ENABLED`, `SPL_QUERY_RAG_SOURCE_DIR`, `SPL_QUERY_RAG_INDEX_DIR`, `SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE`, `SPL_QUERY_RAG_MAX_SNIPPETS`, `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS`, `SPL_QUERY_RAG_FAILURE_MODE` |
| Execution | `INVESTIGATION_QUERY_EXECUTION_ENABLED`, `INVESTIGATION_QUERY_EXECUTOR`, `INVESTIGATION_MAX_QUERIES_PER_ALERT`, `INVESTIGATION_MAX_CONCURRENT_QUERIES` |
| Result interpretation | `QUERY_RESULT_INTERPRETATION_ENABLED`, `QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS`, `QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS`, `QUERY_RESULT_INTERPRETATION_MAX_TOKENS` |
| Splunk connectivity | `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`, `SPLUNK_CA_BUNDLE`, `SPLUNK_SEARCH_ENDPOINT_PATH` |
| Policy | `SPLUNK_SEARCH_ALLOWED_INDEXES`, `SPLUNK_SEARCH_ALLOWED_COMMANDS`, `SPLUNK_SEARCH_DENIED_COMMANDS`, `SPLUNK_SEARCH_MAX_TIME_RANGE`, `SPLUNK_SEARCH_MAX_ROWS`, `SPLUNK_SEARCH_TIMEOUT_SECONDS` |
| MCP | `SPLUNK_MCP_TOOL_NAME` plus injected MCP wiring in code |

## Validation And Rollout

1. Enable SPL generation only and review report output.
2. Optionally curate SPL KB source docs and ingest them with:

   ```bash
   sudo bash scripts/setup_postgres_rag.sh \
     --config-env /etc/notable-analyzer/config.env \
     --spl-query-rag
   ```

3. Set customer-specific allowlists and bounds in a lab config.
4. Enable read-only execution against non-prod or narrow production indexes.
5. Track denied, error, and success outcomes in report metadata.
6. Promote wider index or command policy only after reviewing load and query
   quality.

When `SPL_QUERY_RAG_ENABLED=true`, successful SPL generation includes
`primary_spl_query_grounding_refs` for queries that used SPL KB material. Each
reference contains the source file and section path from the retrieved snippet.

Before REST or MCP execution, the service runs `validate_splunk_query_policy`:
non-empty query, explicit allowed `index=...`, no denied command tokens, at
least one allowed leading pipe command, and bounds on time range, row count,
and timeout.

Code reference:
[`onprem_service/splunk_investigation.py`](../../src/llm_notable_analysis_onprem_systemd/onprem_service/splunk_investigation.py).

