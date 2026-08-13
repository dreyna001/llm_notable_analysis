# Analyst Portal Operations

Operator guide for the GovCloud analyst portal, immutable case runs, and
retrieval-bound case chat.

## Architecture

The production path is contained in `us-gov-east-1`:

```text
Browser -> Regional API Gateway HTTP API -> Portal Lambda
                                      |-> private S3 SPA assets
                                      |-> DynamoDB case/chat state
                                      |-> S3 immutable case archives
                                      |-> VPC-only OpenSearch case index
                                      `-> Bedrock chat synthesis
```

CloudFront and Lambda Function URLs are not part of the GovCloud architecture.
API Gateway routes both `/api/*` and static SPA requests to the portal Lambda.
The Lambda performs bounded, read-only static-object fetches from the private UI
bucket; the UI bucket is separate from case data and blocks public access.

## Customer Inputs

IdP and JWT contract: [`../deployment/PORTAL_JWT_IDENTITY.md`](../deployment/PORTAL_JWT_IDENTITY.md).

- `PortalAuthMode=jwt|iam`
- `PortalJwtIssuer`, `PortalJwtAudience`, and at least one of
  `PortalRequiredAnalystRole` or `PortalRequiredAnalystScope` for JWT mode
- exact `PortalCorsAllowedOrigins`
- `RagTenantId` and the customer deployment/tenant claim mapping
- private subnet IDs and security group IDs for OpenSearch and private customer endpoints
- `OpenSearchEndpoint`, `OpenSearchDomainArn`, and index names
- customer KMS key ARN, log retention, queue retention, object retention, and OpenSearch ISM policy
- approved analysis, embedding, and optional portal chat model IDs/ARNs
- API throttles, Lambda reserved concurrency, and alarm notification topic

## Authentication And Authorization

JWT mode uses an API Gateway JWT authorizer and repeats issuer, audience,
tenant, and analyst grant validation in the Lambda. A valid token without the
configured analyst role or scope receives `403`. IAM mode requires a SigV4
authenticated API Gateway request and remains subject to application tenant
checks. `/api/health` and `/api/ready` are unauthenticated; case and chat routes
are never public.

Static SPA routes are unauthenticated because they contain no customer data or
credentials. The portal role can `s3:GetObject` only for the UI bucket objects;
it cannot list or write that bucket.

## Case And Chat Contracts

- One logical `finding_id` may have multiple immutable analysis runs.
- DynamoDB stores the current pointer and run metadata; S3 stores immutable envelopes.
- OpenSearch case chunks are filtered by both tenant and case ID and retain S3 provenance.
- List cursors require the complete two-part cursor; malformed or partial cursors fail closed.
- `client_request_id` is the chat idempotency key.
- Chat capacity reservation and user/assistant persistence use DynamoDB transactions.
- Retrieved knowledge is advisory and must not be represented as current-alert evidence.

Portal chat is synchronous and is capped at 29 seconds, matching the regional
HTTP API integration boundary. A future asynchronous chat job API would be a
separate product change, not a timeout override.

## Readiness

`GET /api/ready` performs bounded, non-mutating probes for enabled dependencies:

- DynamoDB case index and optional chat tables
- S3 archive access
- embed queue configuration
- signed OpenSearch cluster health when case Q&A is enabled

Readiness fails when an enabled capability is misconfigured or unavailable.
Health remains a process liveness check.

## Deployment

1. Build the frontend under `frontend/analyst-portal`.
2. Upload the generated assets to the stack's private portal UI bucket.
3. Deploy the immutable Lambda image by ECR digest.
4. Configure the exact customer issuer, audience, tenant, analyst grant, CORS origins, VPC resources, KMS key, OpenSearch domain, and model identifiers.
5. Confirm API Gateway throttling, customer network access controls, alarms, and log retention.
6. Verify an unauthorized request receives `401` or `403`, never case data.
7. Verify static assets load, API routes remain authorized, and path traversal is rejected.
8. Run one staged case through archive, embed queue, OpenSearch retrieval, and chat.

## Failure Handling

- Analyzer and embed delivery use SQS with partial-batch failure responses and DLQs.
- Failed or pending case embeddings remain visible for reconciliation.
- OpenSearch or Bedrock chat failure returns a bounded service error and does not mutate case evidence.
- Duplicate chat requests return the previously committed turn rather than consuming capacity twice.
- DLQ redrive is an explicit operator action after the cause is corrected.

## Retention And Recovery

Retention values are set during customer operationalization for S3 objects,
DynamoDB TTLs, logs, queues/DLQs, and OpenSearch documents. Configure an
OpenSearch ISM policy for the four product indexes when the customer requires
document expiry. Backup/restore and cross-region disaster recovery are deferred
internal gaps and are not represented as implemented product capabilities.

## Validation

```bash
python -m pytest tests/test_portal_handler.py tests/test_portal_jwt.py tests/test_case_index.py tests/test_case_chat_history.py -q
cd frontend/analyst-portal
npm test -- --run
npm run build
```

Real GovCloud staging must additionally validate API Gateway JWT behavior,
IAM, KMS, VPC DNS/routing, OpenSearch SigV4 access, Bedrock model access, quotas,
alarms, and end-to-end latency.

## Related Docs

- [`../deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md`](../deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md)
- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../../testing/TESTING.md`](../../testing/TESTING.md)
