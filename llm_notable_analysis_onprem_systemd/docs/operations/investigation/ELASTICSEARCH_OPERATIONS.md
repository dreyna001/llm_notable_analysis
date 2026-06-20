# Elasticsearch Operations

Operator guide for the `elastic_readonly` capability profile: bounded Elasticsearch
Query DSL generation (second LLM call) and read-only `_search` execution. Complements
[`EXECUTIVE_ONPREM_WORKFLOW.md`](../../delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md)
and [`config.env.example`](../../../config.env.example).

## What This Controls

1. **Query DSL generation (`elastic_readonly` profile)**
   After the main analysis call, the service runs a bounded second LLM call that
   emits one `primary_elastic_query` per competing hypothesis (`index_pattern` plus
   `_search` body). Generation does not require Elasticsearch credentials when
   execution is disabled (see **Generation-only lab** below).

2. **Read-only investigation execution (`elastic_readonly` profile)**
   When `INVESTIGATION_QUERY_EXECUTION_ENABLED=true`, the service validates each
   generated query locally, then POSTs to
   `{ELASTICSEARCH_BASE_URL}/{index_pattern}/_search` with `Authorization: ApiKey …`.
   This path does not write to Elasticsearch, does not require Kibana, and does not
   run KQL or ES|QL in v1. `INVESTIGATION_QUERY_EXECUTOR` applies to Splunk only;
   Elastic execution is REST `_search` only.

3. **Query-result interpretation (`QUERY_RESULT_INTERPRETATION_ENABLED`)**
   Optional third bounded LLM call after deterministic execution. Disabled by
   default; does not change query status, counts, or confidence scores.

The profile enables generation and execution together. Profile-controlled flags
override legacy env values at startup.

## Recommended Starting Posture

```bash
CAPABILITY_PROFILES=core,elastic_readonly
INVESTIGATION_QUERY_BACKEND=elasticsearch
ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=false
ELASTICSEARCH_MAX_TIME_RANGE=24h
ELASTICSEARCH_MAX_ROWS=100
ELASTICSEARCH_TIMEOUT_SECONDS=30
INVESTIGATION_MAX_QUERIES_PER_ALERT=6
INVESTIGATION_MAX_CONCURRENT_QUERIES=6
```

Use a read-only Elasticsearch API key limited to `_search` on approved index
patterns. Do not reuse administrative or write-capable keys.

When execution is enabled, `ELASTICSEARCH_BASE_URL` must be HTTPS (no userinfo in
the URL). The service fails startup rather than send an API key over plaintext HTTP.

Keep `QUERY_RESULT_INTERPRETATION_ENABLED=false` until deterministic execution
quality is accepted.

## Customer Decisions

Each deployment should decide:

- which index names or patterns are approved (`ELASTICSEARCH_INDEX_ALLOWLIST`)
- whether wildcard index patterns are allowed (`ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`)
- which timestamp field bounds all searches (`ELASTICSEARCH_TIMESTAMP_FIELD`)
- which fields Query DSL may reference and samples may return
  (`ELASTICSEARCH_ALLOWED_FIELDS`)
- whether dedicated Elastic grounding is required before generation
  (`ELASTICSEARCH_GROUNDING_ENABLED`, `ELASTICSEARCH_GROUNDING_FAILURE_MODE`)
- which local CA bundle is needed for TLS (`ELASTICSEARCH_CA_BUNDLE`)

### One read-only backend per deployment

`spl_readonly` and `elastic_readonly` are mutually exclusive. Startup fails if both
appear in `CAPABILITY_PROFILES`:

```bash
CAPABILITY_PROFILES=core,rag,spl_readonly
# or
CAPABILITY_PROFILES=core,rag,elastic_readonly
```

The active profile sets `INVESTIGATION_QUERY_BACKEND` to `splunk` or
`elasticsearch` respectively.

### Generation-only lab

To review generated Query DSL without live `_search`, do **not** use
`elastic_readonly`. Use manual flags instead:

```bash
CAPABILITY_PROFILES=core
INVESTIGATION_QUERY_BACKEND=elasticsearch
ELASTIC_QUERY_GENERATION_ENABLED=true
INVESTIGATION_QUERY_EXECUTION_ENABLED=false
```

`ELASTICSEARCH_INDEX_ALLOWLIST` is still required. `ELASTICSEARCH_ALLOWED_FIELDS`
is required unless `ELASTICSEARCH_GROUNDING_ENABLED=true`. No API key or HTTPS base
URL is required when execution is off.

## Config Quick Reference

| Setting | Role |
|---------|------|
| `CAPABILITY_PROFILES=…,elastic_readonly` | Enables generation + execution; sets backend to `elasticsearch` |
| `INVESTIGATION_QUERY_BACKEND=elasticsearch` | Active read-only backend (auto-set by profile) |
| `ELASTIC_QUERY_GENERATION_ENABLED` | Legacy/lab flag; profile takes precedence |
| `INVESTIGATION_QUERY_EXECUTION_ENABLED` | Legacy/lab flag; profile takes precedence |
| `INVESTIGATION_MAX_QUERIES_PER_ALERT` | Max hypothesis queries per alert (default `6`, max `24`) |
| `INVESTIGATION_MAX_CONCURRENT_QUERIES` | Process-wide Elastic concurrency cap (default `6`, max `8`) |
| `ELASTICSEARCH_BASE_URL` | HTTPS cluster URL; required when execution is on |
| `ELASTICSEARCH_API_KEY` | Read-only API key; required when execution is on |
| `ELASTICSEARCH_INDEX_ALLOWLIST` | CSV index names/patterns; required when generation or execution is on |
| `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES` | Allow `*` in index patterns (default `false`) |
| `ELASTICSEARCH_TIMESTAMP_FIELD` | Required range-filter field (default `@timestamp`) |
| `ELASTICSEARCH_ALLOWED_FIELDS` | CSV field allowlist; required for execution |
| `ELASTICSEARCH_MAX_TIME_RANGE` | Max span in generated range filters (default `24h`) |
| `ELASTICSEARCH_MAX_ROWS` | Max `body.size` and execution row cap (default `100`, max `1000`) |
| `ELASTICSEARCH_TIMEOUT_SECONDS` | HTTP timeout and injected `body.timeout` (default `30`, max `300`) |
| `ELASTICSEARCH_CA_BUNDLE` | PEM CA path; empty uses system trust store |
| `ELASTICSEARCH_GROUNDING_*` | Dedicated Elastic KB retrieval (see below) |
| `QUERY_RESULT_INTERPRETATION_*` | Optional post-execution LLM interpretation |

Example block:

```bash
INVESTIGATION_QUERY_BACKEND=elasticsearch
ELASTIC_QUERY_GENERATION_ENABLED=false
INVESTIGATION_QUERY_EXECUTION_ENABLED=false
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
INVESTIGATION_MAX_QUERIES_PER_ALERT=6
INVESTIGATION_MAX_CONCURRENT_QUERIES=6
```

## Query Policy

Generated queries use this wrapper shape (one index pattern per hypothesis):

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

Each hypothesis also requires `query_strategy` (`resolve_unknown` or
`check_contradiction`), `why_this_query`, `supports_if`, and `weakens_if`.

### Generation validation (`elastic_query_generation.py`)

Blocks:

- missing or placeholder `index_pattern`
- index patterns outside `ELASTICSEARCH_INDEX_ALLOWLIST`
- comma-, slash-, backslash-, `?`, or `#`-delimited multi-index expressions
- wildcard index patterns when `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES=false`
- missing bounded range on `ELASTICSEARCH_TIMESTAMP_FIELD` (supports `now-…` math
  and ISO datetimes within `ELASTICSEARCH_MAX_TIME_RANGE`)
- `body.size` above `ELASTICSEARCH_MAX_ROWS` (omitted size defaults to the cap at validation)
- fields outside `ELASTICSEARCH_ALLOWED_FIELDS`, unless present in the alert text or
  `ELASTICSEARCH_GROUNDING_CONTEXT`
- when grounding context is non-empty: index patterns and fields must appear in the
  alert or grounding context (stricter grounding mode)
- denied DSL keys anywhere in the body, including: `aggs`, `aggregations`,
  `query_string`, `simple_query_string`, `regexp`, `wildcard`, `script`,
  `script_fields`, `script_score`, `runtime_mappings`, `highlight`, `knn`,
  `more_like_this`, `collapse`, `rescore`, `suggest`, `pipeline`, `delete`, `update`

Allowed filter-style clauses include `bool`, `term`, `terms`, `match`,
`match_phrase`, `range`, `prefix`, and `exists`.

### Execution normalization (`elasticsearch_investigation.py`)

Before transport, execution:

- caps or injects `body.size` to the configured row limit
- sets `_source` to `ELASTICSEARCH_ALLOWED_FIELDS`
- injects `body.timeout` and `body.terminate_after` from configured caps
- re-validates through the same contract with `require_elastic_grounding=false`

Denied queries return `status=denied` without a network call.

Concurrency: up to `INVESTIGATION_MAX_QUERIES_PER_ALERT` queries per alert, with a
process-wide semaphore limiting in-flight `_search` calls to
`INVESTIGATION_MAX_CONCURRENT_QUERIES`.

Normalized results expose up to five sample rows, twelve columns per row, and one
hundred sixty characters per cell value.

## Elastic Grounding

Elastic grounding is separate from general SOC RAG (`rag` profile). It supplies
`ELASTICSEARCH_GROUNDING_CONTEXT` for index catalogs, field mappings, timestamp
conventions, and approved Query DSL examples.

```bash
ELASTICSEARCH_GROUNDING_ENABLED=false
ELASTICSEARCH_GROUNDING_SOURCE_DIR=/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs
ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE=elasticsearch_query_chunks
ELASTICSEARCH_GROUNDING_MAX_SNIPPETS=4
ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS=1600
ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress
```

| Mode | Behavior |
|------|----------|
| `suppress` (default) | Omit generated Elastic queries when grounding is enabled but retrieval fails |
| `fallback_to_ungrounded` | Continue generation without grounding context (lab / lower-risk only) |

When grounding retrieval succeeds, validators require index patterns and fields to
appear in the alert or grounding snippets. `SOC_OPERATIONAL_CONTEXT` does not
authorize environment-specific Elastic tokens.

KB templates, ingest, and retrieval tuning:
[`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) (sections
**Add Or Update Elasticsearch Query KB Documents** through
**Elasticsearch Query KB — Retrieval Tuning**).

Validated responses may include per-hypothesis `primary_elastic_query_grounding_refs`
in structured output; the shipped markdown report does not render those refs today.

## Customer Onboarding — Elasticsearch Query Grounding

Complete with Elastic owners **before** setting `ELASTICSEARCH_GROUNDING_ENABLED=true`
and before enabling `elastic_readonly` in production scope.

| Item | Required | Notes |
|------|----------|-------|
| `ELASTICSEARCH_INDEX_ALLOWLIST` | Yes | Must match KB index patterns |
| `ELASTICSEARCH_ALLOWED_FIELDS` | Yes for execution | Code-enforced; KB supplements, does not replace |
| `ELASTICSEARCH_TIMESTAMP_FIELD` | Yes | Usually `@timestamp` |
| ECS vs custom field mapping | Yes | Document in Elastic query KB |
| Approved Query DSL examples | Recommended | bool/filter patterns only |
| Read-only API key scope | Yes if executing | HTTPS base URL and CA bundle |
| Representative notables | Yes | 3–5 per major index/data source |
| Execution scope | Yes | Profile enables both; use manual flags for generation-only |
| Failure mode | Yes | Default `ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress` |
| KB owner and review cadence | Yes | Approve doc changes before rebuild |

### Splunk vs Elastic — field expectations

- **Splunk:** validators gate `index=`, `sourcetype=`, macros, datamodels. Other
  SPL field names may come from the alert or SPL grounding context.
- **Elastic:** validators gate index patterns **and** field names against config
  allowlists (plus alert/grounding tokens). Set `ELASTICSEARCH_ALLOWED_FIELDS`
  explicitly.

### Rollout checklist

1. [ ] Elastic owners approve index and field allowlists
2. [ ] Elastic owners approve Elastic query KB source doc set
3. [ ] Stage docs under `elasticsearch_source_docs`; run corpus ingest (see
       [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md))
4. [ ] Run Elastic query KB quality checklist
5. [ ] Set `CAPABILITY_PROFILES=core,elastic_readonly` (or generation-only manual flags)
6. [ ] Enable `ELASTICSEARCH_GROUNDING_ENABLED=true` when KB is ready
7. [ ] Process representative notables; review generated Query DSL with Elastic owners
8. [ ] If executing: validate read-only API key, TLS, row/time/concurrency caps
9. [ ] Record onboarding date, owner, and failure mode in change notes

## Validation And Rollout

1. Start with `CAPABILITY_PROFILES=core`.
2. Configure `ELASTICSEARCH_INDEX_ALLOWLIST`, `ELASTICSEARCH_TIMESTAMP_FIELD`, and
   `ELASTICSEARCH_ALLOWED_FIELDS`.
3. Create a read-only API key scoped to approved index patterns.
4. Confirm `ELASTICSEARCH_BASE_URL` is HTTPS and TLS verifies (system store or
   `ELASTICSEARCH_CA_BUNDLE`).
5. Enable `CAPABILITY_PROFILES=core,elastic_readonly` in lab scope.
6. Run unit tests before live validation:

```bash
python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests/onprem_service -p "test_elastic*.py" -v
```

7. Validate with approved test notables; review generated Query DSL with the Elastic owner.
8. Raise row/time/concurrency limits only after measuring latency and cluster impact.

Unit tests must not require live Elasticsearch. Live validation is an operator smoke
test after policy and credentials are approved.

## Related Docs

- [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
- [`CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md)
- [`RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`config.env.example`](../../../config.env.example)
