# Security Operations

## Runtime Posture

- Keep external-action profiles disabled until a customer-approved rollout plan is in place.
- Store Splunk, Elasticsearch, ServiceNow, MCP, and approval HMAC secrets in AWS Secrets Manager.
- Use HTTPS endpoints without userinfo. Private or local IP endpoints require `ALLOW_PRIVATE_OUTBOUND_ENDPOINTS=true`.
- Treat generated SPL, Elasticsearch Query DSL, and ticket payloads as untrusted until policy validation passes.

## External Action Gates

- Splunk writeback uses validated finding identifiers and can require payload/key agreement with `SPLUNK_REQUIRE_PAYLOAD_FINDING_ID=true`.
- ServiceNow create requires `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`, a signed approval payload, and `SERVICENOW_APPROVAL_HMAC_SECRET_ARN`.
- DynamoDB idempotency should stay enabled for writeback and create flows.

## Data Handling

- Raw S3 input is size bounded before prompt construction.
- Splunk result samples drop `_raw`; set `SPLUNK_SEARCH_ALLOWED_FIELDS` to restrict sample fields further.
- Elasticsearch result samples are restricted to `ELASTICSEARCH_ALLOWED_FIELDS`.

## Deployment Checks

1. Confirm S3 buckets have public access blocked and server-side encryption enabled.
2. Confirm Lambda reserved concurrency is set to protect downstream systems.
3. Confirm IAM policies grant only required S3, Secrets Manager, Bedrock, and DynamoDB permissions.
4. Confirm denied query/action paths do not make outbound calls.
