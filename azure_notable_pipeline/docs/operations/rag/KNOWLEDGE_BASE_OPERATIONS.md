# Azure AI Search knowledge-base operations

Azure AI Search provides advisory grounding for general RAG, SPL generation,
Elasticsearch generation, and portal chat. Retrieved material is untrusted
advisory context, never current-case evidence.

## Provisioning contract

Create customer-owned indexes named by `RAG_AZURE_SEARCH_INDEX`,
`SPL_QUERY_AZURE_SEARCH_INDEX`, and
`ELASTICSEARCH_GROUNDING_AZURE_SEARCH_INDEX`. An index may be shared only when
its source governance, schema, access, and lifecycle are intentionally shared.
Grant the relevant Function identity the minimum Search data-reader role; use
managed identity, not admin/query keys.

Documents must expose bounded text plus stable source and section metadata.
Chunk outside the request path, reject unsupported/oversized content, retain
source attribution, and version ingestion. Do not ingest customer cases into a
procedural KB. Define source owner, classification, refresh cadence, deletion
SLA, indexer identity, and failed-ingestion dead letter before enablement.

## Validation and promotion

1. Load a non-production index from approved synthetic/runbook content.
2. Verify exact source/section attribution, empty-result behavior, query bounds,
   tenant isolation, and managed-identity access.
3. If semantic rerank is enabled, qualify SKU/billing behavior and confirm the
   documented plain-Search fallback. It is never a second LLM.
4. Run staging with RAG/SPL/Elastic profiles individually, then together.
5. Record index schema/version and ingestion checkpoint in the deployment
   record before promoting the index name.

Monitor query failure/latency, throttling, empty-result drift, ingestion age,
document count, and semantic-rerank rejection. `suppress` failure mode continues
without grounding and must remain visible in report metadata; `fail_closed`
stops the affected workflow.

To roll back, redeploy the prior immutable index name/version. Do not rebuild an
in-use index destructively. Remove a compromised source, rebuild, validate, and
then switch configuration. Search outage recovery never authorizes claiming
ungrounded content as case evidence.
