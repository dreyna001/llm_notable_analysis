# Elasticsearch Operations

Operator guide for the `elastic_readonly` capability profile on AWS: bounded
Elasticsearch Query DSL generation (second Bedrock call), optional Elastic
grounding from a dedicated tenant-scoped OpenSearch dictionary index, and read-only `_search`
execution from Lambda. Complements
[`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) and
[`../../README.md`](../../README.md) deploy parameters.

## What This Controls

1. **Query DSL generation (`elastic_readonly` profile)**
   After the main analysis call, Lambda runs a bounded second Bedrock call that
   emits one `primary_elastic_query` per competing hypothesis (`index_pattern`
   plus `_search` body). Generation does not require Elasticsearch credentials
   when execution is disabled (see **Generation-only lab** below).

2. **Read-only investigation execution (`elastic_readonly` profile)**
   When `INVESTIGATION_QUERY_EXECUTION_ENABLED=true`, Lambda validates each
   generated query locally, then POSTs to
   `{ELASTICSEARCH_BASE_URL}/{index_pattern}/_search` with
   `Authorization: ApiKey …`. This path does not write to Elasticsearch, does
   not require Kibana, and does not run KQL or ES|QL in v1.
   `INVESTIGATION_QUERY_EXECUTOR` applies to Splunk only; Elastic execution is
   REST `_search` only.

3. **Query-result interpretation (`QUERY_RESULT_INTERPRETATION_ENABLED`)**
   Optional third bounded Bedrock call after deterministic execution. Disabled
   by default; does not change query status, counts, or confidence scores.

The `elastic_readonly` profile enables generation and execution together and
sets `INVESTIGATION_QUERY_BACKEND=elasticsearch`. Profile-controlled flags
override legacy env values at Lambda startup.

## Recommended Starting Posture

Keep Elasticsearch generation and execution disabled for the first `core`
rollout. Enable only after the customer has approved the Elasticsearch base URL,
index allowlist, field allowlist, row cap, time range, network path, API key
secret, and approved dictionary content used for Elastic grounding.

For parity deployments, start with:

- `CapabilityProfiles=core,elastic_readonly` (Lambda env:
  `CAPABILITY_PROFILES=core,elastic_readonly`)
- Narrow `ElasticsearchIndexAllowlist` values such as `security-*` or
  `logs-endpoint-*`.
- A small `ElasticsearchMaxRows` value for initial validation.
- `ElasticsearchAllowWildcardIndexes=false` until wildcard patterns are
  explicitly approved.
- `LambdaTimeoutSeconds=900` and `LambdaMemorySize=1024` when RAG plus
  read-only investigation are both enabled.

Do not enable `spl_readonly` and `elastic_readonly` together. The AWS runtime
supports one read-only investigation backend per deployment; startup fails if
both profiles appear in `CAPABILITY_PROFILES`.

Use a read-only Elasticsearch API key limited to `_search` on approved index
patterns. Store it in Secrets Manager; do not place the key in SAM parameters,
CloudFormation templates, Lambda environment variables, logs, or reports.

When execution is enabled, `ElasticsearchBaseUrl` must be HTTPS. Lambda fails
startup rather than send an API key over plaintext HTTP. For clusters on
private IP ranges, set `AllowPrivateOutboundEndpoints=true` and confirm the
Lambda VPC or network path can reach the endpoint.

Keep `QUERY_RESULT_INTERPRETATION_ENABLED=false` until deterministic execution
quality is accepted.

## Customer Decisions

- Which Elasticsearch endpoint should Lambda call, and what VPC, NAT,
  PrivateLink, or customer routing is required?
- Which index patterns are approved for read-only investigation?
- Which fields are safe to use in generated queries and returned sample rows?
- Which timestamp field defines the query time window?
- Which approved S3 dictionary sources and manifests define Elastic indexes,
  fields, and timestamp guidance?
- What Secrets Manager secret holds the Elasticsearch API key?
- Whether wildcard index patterns are allowed
  (`ElasticsearchAllowWildcardIndexes`).

### One read-only backend per deployment

`spl_readonly` and `elastic_readonly` are mutually exclusive:

```text
CapabilityProfiles=core,rag,spl_readonly
# or
CapabilityProfiles=core,rag,elastic_readonly
```

The active profile sets `INVESTIGATION_QUERY_BACKEND` to `splunk` or
`elasticsearch` respectively.

### Generation-only lab

To review generated Query DSL without live `_search`, do **not** use
`elastic_readonly`. Use manual flags instead:

```text
CAPABILITY_PROFILES=core
INVESTIGATION_QUERY_BACKEND=elasticsearch
ELASTIC_QUERY_GENERATION_ENABLED=true
INVESTIGATION_QUERY_EXECUTION_ENABLED=false
```

`ELASTICSEARCH_INDEX_ALLOWLIST` is still required for contract validation.
`ELASTICSEARCH_ALLOWED_FIELDS` is required unless
`ELASTICSEARCH_GROUNDING_ENABLED=true` with usable grounding snippets. No API
key or HTTPS base URL is required at startup when execution is off.

## Config Quick Reference

SAM and CloudFormation parameters are the official deployment path. Lambda
environment variables are the runtime representation of those parameters.

| SAM / CloudFormation parameter | Lambda env var | Role |
|--------------------------------|----------------|------|
| `CapabilityProfiles=…,elastic_readonly` | `CAPABILITY_PROFILES` | Enables generation + execution; sets backend to `elasticsearch` |
| — | `INVESTIGATION_QUERY_BACKEND` | Active read-only backend (auto-set by profile) |
| — | `ELASTIC_QUERY_GENERATION_ENABLED` | Legacy/lab flag; profile takes precedence |
| — | `INVESTIGATION_QUERY_EXECUTION_ENABLED` | Legacy/lab flag; profile takes precedence |
| `InvestigationMaxQueriesPerAlert` | `INVESTIGATION_MAX_QUERIES_PER_ALERT` | Max hypothesis queries per alert (default `6`, max `24`) |
| `InvestigationMaxConcurrentQueries` | `INVESTIGATION_MAX_CONCURRENT_QUERIES` | Process-wide Elastic concurrency cap (default `6`, max `8`) |
| `ElasticsearchBaseUrl` | `ELASTICSEARCH_BASE_URL` | HTTPS cluster URL; required when execution is on |
| `ElasticsearchApiKeySecretArn` | `ELASTICSEARCH_API_KEY_SECRET_ARN` | Secrets Manager ARN; plain string or JSON with `api_key` or `token` |
| `ElasticsearchIndexAllowlist` | `ELASTICSEARCH_INDEX_ALLOWLIST` | CSV index names/patterns; required when execution is on |
| `ElasticsearchAllowWildcardIndexes` | `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES` | Allow `*` in index patterns (default `false`) |
| `ElasticsearchTimestampField` | `ELASTICSEARCH_TIMESTAMP_FIELD` | Required range-filter field (default `@timestamp`) |
| `ElasticsearchAllowedFields` | `ELASTICSEARCH_ALLOWED_FIELDS` | CSV field allowlist; required when execution is on |
| `ElasticsearchMaxTimeRange` | `ELASTICSEARCH_MAX_TIME_RANGE` | Max span in generated range filters (default `24h`) |
| `ElasticsearchMaxRows` | `ELASTICSEARCH_MAX_ROWS` | Max `body.size` and execution row cap (default `100`, max `1000`) |
| `ElasticsearchTimeoutSeconds` | `ELASTICSEARCH_TIMEOUT_SECONDS` | HTTP timeout and injected `body.timeout` (default `30`, max `300`) |
| `ElasticsearchGroundingEnabled` | `ELASTICSEARCH_GROUNDING_ENABLED` | Enables the tenant-scoped Elasticsearch dictionary index in OpenSearch |
| — | `ELASTICSEARCH_GROUNDING_MAX_SNIPPETS` | Max grounding snippets (default `4`; env-only, not a SAM parameter) |
| — | `ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS` | Grounding render budget (default `1600`; env-only) |
| — | `ELASTICSEARCH_GROUNDING_FAILURE_MODE` | `suppress` or `fallback_to_ungrounded` (default `suppress`) |
| `AllowPrivateOutboundEndpoints` | `ALLOW_PRIVATE_OUTBOUND_ENDPOINTS` | Allow HTTPS to private/local IPs (default `false`) |
| — | `QUERY_RESULT_INTERPRETATION_ENABLED` | Optional post-execution LLM interpretation (default `false`; env-only) |

## Validation And Rollout

1. Deploy with `CapabilityProfiles=core` and confirm the base S3 report path.
2. Upload approved dictionary sources and a versioned ingestion manifest, then
   confirm the Elastic dictionary index contains only approved index, field,
   and timestamp guidance.
3. Store the API key in Secrets Manager as either a plain secret string or JSON
   with `api_key` or `token`.
4. Enable `core,elastic_readonly` in a non-production stack with a narrow index
   allowlist and row limit.
5. Verify generated Query DSL appears in JSON and markdown reports under
   `competing_hypotheses[].primary_elastic_query`.
6. Confirm denied queries return `status=denied` and do not make a network call.
7. Confirm `_search` results are normalized under `investigation_query_results`
   with `executor=elasticsearch`.
8. Confirm report metadata includes `investigation_query_backend=elasticsearch`,
   `investigation_query_executor=elasticsearch`, and
   `investigation_query_result_count`.

Unit test commands (from repository root):

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_elastic_query_generation.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_elasticsearch_investigation.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_config.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v
```

See [`../../testing/TESTING.md`](../../testing/TESTING.md) for stack-level
`elastic_readonly` smoke checks.

## Safety Bounds

Generated Query DSL is policy-validated before execution. The validator rejects
unapproved index patterns, missing timestamp bounds, excessive sizes, unsupported
time windows, placeholder text, and risky DSL features such as scripts,
`query_string`, wildcard clauses, aggregations, highlighting, and runtime
mappings.

Before transport, execution caps or injects `body.size`, sets `_source` to
`ELASTICSEARCH_ALLOWED_FIELDS`, and injects `body.timeout` and
`body.terminate_after` from configured caps. TLS verification uses the Lambda
runtime system trust store (`verify=True`); there is no custom CA bundle setting
in the AWS pipeline.

Returned sample rows are field-filtered and bounded (up to five rows, twelve
columns per row, one hundred sixty characters per cell) before they are passed
into reports or optional query-result interpretation.

## IAM And Secrets

The Lambda role needs `secretsmanager:GetSecretValue` only for
`ElasticsearchApiKeySecretArn` when configured (not the `*` placeholder). If
Elastic grounding is enabled, the Lambda role also needs signed HTTP access
scoped to the configured OpenSearch domain and Elastic dictionary index.

The Elasticsearch API key must not be placed directly in SAM parameters,
CloudFormation templates, Lambda environment variables, logs, or reports.

## Related Docs

- [`../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../../testing/TESTING.md`](../../testing/TESTING.md)
