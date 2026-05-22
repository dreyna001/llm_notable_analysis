# Elasticsearch Operations

## What This Controls

The `elastic_readonly` capability profile enables generated Elasticsearch Query
DSL plus bounded read-only `_search` execution. It mirrors the Splunk read-only
investigation path, but uses Elastic-specific index patterns, field mappings,
and query policy controls.

This path does not write to Elasticsearch, does not require Kibana, and does not
run KQL or ES|QL in v1.

## Recommended Starting Posture

Start with:

```bash
CAPABILITY_PROFILES=core,elastic_readonly
INVESTIGATION_QUERY_BACKEND=elasticsearch
ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=false
ELASTICSEARCH_MAX_TIME_RANGE=24h
ELASTICSEARCH_MAX_ROWS=100
ELASTICSEARCH_TIMEOUT_SECONDS=30
```

Use a read-only Elasticsearch API key limited to `_search` on approved index
patterns only. Do not reuse administrative or write-capable API keys.

## Customer Decisions

Each deployment should decide:

- which index names or index patterns are approved for investigation queries
- whether wildcard index patterns are allowed
- which timestamp field should bound all generated searches
- whether the deployment uses ECS field names, custom field names, or both
- which fields generated Query DSL may reference
- whether Elastic-specific grounding is required before generated queries can be emitted
- which local CA bundle is needed for TLS verification, if any

For v1, choose one read-only investigation backend per deployment:

```bash
CAPABILITY_PROFILES=core,rag,spl_readonly
# or
CAPABILITY_PROFILES=core,rag,elastic_readonly
```

Do not enable `spl_readonly` and `elastic_readonly` together.

## Config Quick Reference

```bash
INVESTIGATION_QUERY_BACKEND=elasticsearch
ELASTIC_QUERY_GENERATION_ENABLED=false
ELASTICSEARCH_BASE_URL=https://elastic.internal:9200
ELASTICSEARCH_API_KEY=
ELASTICSEARCH_INDEX_ALLOWLIST=logs-auth,security-*
ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=false
ELASTICSEARCH_TIMESTAMP_FIELD=@timestamp
ELASTICSEARCH_ALLOWED_FIELDS=@timestamp,user.name,host.name,source.ip,destination.ip,event.action,event.category
ELASTICSEARCH_MAX_TIME_RANGE=24h
ELASTICSEARCH_MAX_ROWS=100
ELASTICSEARCH_TIMEOUT_SECONDS=30
ELASTICSEARCH_CA_BUNDLE=
```

When `elastic_readonly` is selected, the profile enables Elastic query
generation and read-only investigation execution. Low-level flags remain for lab
configs, but profiles are the preferred operator workflow.

## Query Policy

Generated Elastic queries must use this wrapper shape:

```json
{
  "index_pattern": "logs-auth",
  "body": {
    "size": 25,
    "query": {
      "bool": {
        "filter": [
          {
            "range": {
              "@timestamp": {
                "gte": "now-24h",
                "lte": "now"
              }
            }
          }
        ]
      }
    }
  }
}
```

Policy validation blocks:

- missing `index_pattern`
- index patterns outside `ELASTICSEARCH_INDEX_ALLOWLIST`
- wildcard index patterns unless `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=true`
- missing bounded range filter on `ELASTICSEARCH_TIMESTAMP_FIELD`
- `size` above `ELASTICSEARCH_MAX_ROWS`
- fields outside `ELASTICSEARCH_ALLOWED_FIELDS`, unless grounded by approved Elastic context
- scripting or runtime mutation features such as `script`, `script_fields`, or `runtime_mappings`

## Elastic Grounding

Elastic grounding is separate from general SOC RAG. It should contain
customer-owned facts needed to safely generate useful Query DSL:

- index catalogs and approved index patterns
- ECS field mappings
- custom field dictionaries
- timestamp field conventions
- approved query examples
- runbooks describing which indexes cover which alert types

```bash
ELASTICSEARCH_GROUNDING_ENABLED=false
ELASTICSEARCH_GROUNDING_SOURCE_DIR=/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs
ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE=elasticsearch_query_chunks
ELASTICSEARCH_GROUNDING_MAX_SNIPPETS=4
ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS=1600
ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress
```

Use `suppress` when operators require grounded index and field usage. Use
`fallback_to_ungrounded` only for lab or lower-risk deployments where
alert-only generic queries are acceptable during grounding outages.

## Validation And Rollout

1. Start with `CAPABILITY_PROFILES=core`.
2. Configure `ELASTICSEARCH_INDEX_ALLOWLIST`, `ELASTICSEARCH_TIMESTAMP_FIELD`,
   and `ELASTICSEARCH_ALLOWED_FIELDS`.
3. Create a read-only API key scoped to approved index patterns.
4. Enable `CAPABILITY_PROFILES=core,elastic_readonly` in a lab or non-production
   scope.
5. Run unit tests and fake-response adapter tests before any live validation.
6. Validate with a small set of approved test notables and review generated
   Query DSL with the Elastic owner.
7. Raise row/time/concurrency limits only after measuring latency and cluster
   impact.

Unit tests must not require live Elasticsearch. Live validation is an operator
smoke test after policy and credentials are approved.

## Related Docs

- [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md)
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
- [`../../config.env.example`](../../config.env.example)
