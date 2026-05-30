# Elasticsearch Operations

## What This Controls

This guide covers optional Elasticsearch Query DSL generation,
Elasticsearch-specific Bedrock Knowledge Base grounding, and bounded read-only
`_search` execution for AWS deployments.

## Recommended Starting Posture

Keep Elasticsearch generation and execution disabled for the first `core`
rollout. Enable it only after the customer has approved the Elasticsearch base
URL, index allowlist, field allowlist, row cap, time range, network path, API key
secret, and Knowledge Base content used for Elastic grounding.

For parity deployments, start with:

- `CAPABILITY_PROFILES=core,elastic_readonly`
- Narrow `ELASTICSEARCH_INDEX_ALLOWLIST` values such as `security-*` or
  `logs-endpoint-*`.
- A small `ELASTICSEARCH_MAX_ROWS` value for initial validation.
- `LambdaTimeoutSeconds=900` and `LambdaMemorySize=1024` when RAG plus
  read-only investigation are both enabled.

Do not enable `spl_readonly` and `elastic_readonly` together. The AWS runtime
supports one read-only investigation backend per deployment profile.

## Customer Decisions

- Which Elasticsearch endpoint should Lambda call, and what VPC, NAT,
  PrivateLink, or customer routing is required?
- Which index patterns are approved for read-only investigation?
- Which fields are safe to use in generated queries and returned sample rows?
- Which timestamp field defines the query time window?
- Which Bedrock Knowledge Base contains approved Elastic index and field
  guidance?
- What Secrets Manager secret holds the Elasticsearch API key?

## Config Quick Reference

- `CAPABILITY_PROFILES=core,elastic_readonly`
- `ELASTIC_QUERY_GENERATION_ENABLED`
- `INVESTIGATION_QUERY_EXECUTION_ENABLED`
- `INVESTIGATION_QUERY_BACKEND=elasticsearch`
- `ELASTICSEARCH_BASE_URL`
- `ELASTICSEARCH_API_KEY_SECRET_ARN`
- `ELASTICSEARCH_INDEX_ALLOWLIST`
- `ELASTICSEARCH_ALLOWED_FIELDS`
- `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`
- `ELASTICSEARCH_TIMESTAMP_FIELD`
- `ELASTICSEARCH_MAX_TIME_RANGE`
- `ELASTICSEARCH_MAX_ROWS`
- `ELASTICSEARCH_TIMEOUT_SECONDS`
- `ELASTICSEARCH_GROUNDING_ENABLED`
- `ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID`
- `ELASTICSEARCH_GROUNDING_MAX_SNIPPETS`
- `ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS`
- `ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress|fallback_to_ungrounded`

SAM and CloudFormation parameters are the official deployment path. Lambda
environment variables are the runtime representation of those parameters.

## Validation And Rollout

1. Deploy with `CAPABILITY_PROFILES=core` and confirm the base S3 report path.
2. Create or select the Elastic grounding Knowledge Base and confirm its
   snippets contain only approved index, field, and timestamp guidance.
3. Store the API key in Secrets Manager as either a plain secret string or JSON
   with `api_key` or `token`.
4. Enable `core,elastic_readonly` in a non-production stack with a narrow index
   allowlist and row limit.
5. Verify generated Query DSL appears in JSON and markdown reports.
6. Confirm denied queries do not make a network call.
7. Confirm `_search` results are normalized under
   `investigation_query_results`.

Unit test commands:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_elastic_query_generation.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_elasticsearch_investigation.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v
```

## Safety Bounds

Generated Query DSL is policy-validated before execution. The validator rejects
unapproved index patterns, missing timestamp bounds, excessive sizes, unsupported
time windows, placeholder text, and risky DSL features such as scripts,
`query_string`, wildcard clauses, aggregations, highlighting, and runtime
mappings.

Returned sample rows are field-filtered and bounded before they are passed into
reports or optional query-result interpretation.

## IAM And Secrets

The Lambda role needs `secretsmanager:GetSecretValue` only for
`ELASTICSEARCH_API_KEY_SECRET_ARN` when configured. If Elastic grounding is
enabled, the Lambda role also needs `bedrock:Retrieve` scoped to the configured
Knowledge Base ARN.

The Elasticsearch API key must not be placed directly in SAM parameters,
CloudFormation templates, Lambda environment variables, logs, or reports.

## Related Docs

- `../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`
- `KNOWLEDGE_BASE_OPERATIONS.md`
- `RAG_OPERATIONS.md`
- `SECURITY_OPERATIONS.md`
