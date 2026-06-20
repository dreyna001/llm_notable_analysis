# AWS RAG Operations

For Bedrock Knowledge Base source content and sync lifecycle, see
[`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md).

## What This Controls

The `rag` capability profile adds advisory SOC context from an Amazon Bedrock
Knowledge Base before the main notable-analysis Bedrock call. `lambda_handler.py`
calls `retrieve_soc_context()` in `bedrock_kb_retrieval.py`, which uses the
Bedrock Agent Runtime `Retrieve` API (`bedrock-agent-runtime`). Retrieved
snippets are rendered with source labels, passed to `BedrockAnalyzer.analyze_ttp()`
as `advisory_context`, and injected under the stable prompt header
`SOC_OPERATIONAL_CONTEXT`. Retrieved content is not direct alert evidence.

**SPL query grounding is separate.** A dedicated Knowledge Base and
`SPL_QUERY_RAG_*` settings govern Splunk token grounding in the SPL-generation
call. See [`../investigation/SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md).

## Recommended Starting Posture

- Keep `CapabilityProfiles=core` for first deployment.
- Add the `rag` profile only after the general Knowledge Base source documents
  are curated and approved by the customer.
- Set `RagBedrockKbId` to the approved Knowledge Base id. The SAM template
  grants `bedrock:Retrieve` only when this id is non-empty.
- Use `RagFailureMode=suppress` (default) so analysis continues when retrieval
  is unavailable.

## Customer Decisions

- Which Bedrock Knowledge Base contains approved SOC SOPs, escalation guidance,
  field dictionaries, detection notes, and runbooks?
- Who owns source document freshness and removal?
- Should retrieval failures suppress context (`suppress`) or fail the analysis
  (`fail_closed`)?

## Config Quick Reference

Set values through SAM/CloudFormation parameters in
`deploy/aws/template-sam.yaml`. Do not manually edit Lambda environment
variables in the console as the normal workflow.

| Area | SAM parameter | Lambda env |
|------|---------------|------------|
| Profile enablement | `CapabilityProfiles=core,rag` | `CAPABILITY_PROFILES` (sets `RAG_ENABLED=true`) |
| Legacy enablement | `RagEnabled=true` | `RAG_ENABLED` (used only when the `rag` profile is not selected) |
| Knowledge Base | `RagBedrockKbId` | `RAG_BEDROCK_KB_ID` |
| Retrieval size | `RagMaxSnippets` | `RAG_MAX_SNIPPETS` |
| Context budget | `RagContextBudgetChars` | `RAG_CONTEXT_BUDGET_CHARS` |
| Failure behavior | `RagFailureMode` | `RAG_FAILURE_MODE` (`suppress` or `fail_closed`) |

**Template defaults (`template-sam.yaml`):**

| Parameter | Default |
|-----------|---------|
| `RagEnabled` | `false` |
| `RagBedrockKbId` | (empty) |
| `RagMaxSnippets` | `4` (range 1-20) |
| `RagContextBudgetChars` | `1600` (range 1-10000) |
| `RagFailureMode` | `suppress` |

When the `rag` profile is selected, profile flags take precedence over
`RagEnabled`. Prefer `CapabilityProfiles=core,rag` plus `RagBedrockKbId`; do
not rely on a standalone `RagEnabled=true` in production.

Retrieval passes `alert_text` as the query and requests
`vectorSearchConfiguration.numberOfResults` equal to `RAG_MAX_SNIPPETS`.
Rendered context is capped at `RAG_CONTEXT_BUDGET_CHARS`.

**Failure behavior (`bedrock_kb_retrieval.py`):**

| Mode | Missing KB id | Retrieve API error | No snippets |
|------|---------------|--------------------|-------------|
| `suppress` | Continue; `rag_status=failed` | Continue; `rag_status=failed` | Continue; `rag_status=no_match` |
| `fail_closed` | Raise; analysis fails | Raise; analysis fails | Continue; `rag_status=no_match` |

On success or soft failure, JSON report metadata includes `rag_status`,
`rag_snippet_count`, and optionally `rag_message`.

The template also exposes `RagRerankEnabled`, `RagRerankModel`, and
`RagRerankModelFallback` as Lambda env vars. General SOC Bedrock KB retrieval
does not call rerank today.

## Validation And Rollout

1. Deploy with `CapabilityProfiles=core` and verify markdown/JSON output.
2. Populate and approve the Bedrock Knowledge Base; confirm it is queryable in
   the deployment region.
3. Redeploy with `CapabilityProfiles=core,rag` and `RagBedrockKbId=<kb-id>`.
4. Confirm the Lambda role has `bedrock:Retrieve` on that Knowledge Base ARN.
5. Process a representative notable. Confirm JSON metadata has `rag_status` and
   `rag_snippet_count`, and that report text treats retrieved SOP content as
   advisory rather than observed alert facts.
6. Set `RagFailureMode=fail_closed` only when operators require retrieval
   availability for every analysis.

## Related Docs

- [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md)
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md)
- [`../investigation/SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
