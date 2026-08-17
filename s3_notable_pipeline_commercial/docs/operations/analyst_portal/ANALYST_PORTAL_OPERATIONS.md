# Analyst Portal Operations

Canonical operator guide for the commercial AWS analyst portal: architecture,
authentication boundaries, case/chat contracts, and readiness. SPA build and
upload: [`../../../frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md).
Profile flags and SAM parameters: [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
(`analyst_portal`).

## Architecture

Production path in `us-east-1` (no CloudFront, no Lambda Function URLs):

```text
Browser -> Regional API Gateway HTTP API -> Portal Lambda
                                      |-> private S3 SPA assets
                                      |-> DynamoDB case/chat state
                                      |-> S3 immutable case archives
                                      |-> VPC-only OpenSearch case index
                                      `-> Bedrock chat synthesis
```

Regional API Gateway routes `/api/*` and static SPA requests to the portal Lambda.
The Lambda performs bounded, read-only `s3:GetObject` from the private UI bucket
(separate from case data; blocks public access).

## Customer Inputs

IdP and JWT contract: [`../deployment/PORTAL_JWT_IDENTITY.md`](../deployment/PORTAL_JWT_IDENTITY.md).

**Backend**

- `PortalAuthMode=jwt|iam` — `jwt` for generic OIDC access tokens (analyst
  browsers); `iam` for SigV4 API automation only (not browser analysts)
- `PortalJwtIssuer`, `PortalJwtAudience`, and at least one of
  `PortalRequiredAnalystRole` or `PortalRequiredAnalystScope` (JWT mode)
- optional `PortalJwtTenantId` aligned with the Entra tenant id
- exact `PortalCorsAllowedOrigins` / `PORTAL_CORS_ALLOWED_ORIGINS`
- `RagTenantId` and deployment/tenant claim mapping

**Frontend (SPA build, JWT backend)**

- `VITE_PORTAL_AUTH_MODE=manual|entra|none` — `manual` default; `entra` for
  MSAL PKCE Entra sign-in; `none` when no browser token acquisition is desired
- Entra production: customer Entra tenant id, API app client id/audience, SPA
  client id, delegated API scope, optional analyst app role, exact redirect and
  logout URIs, portal origin in CORS — see PORTAL_JWT_IDENTITY.md
- use API **access tokens**, not Entra ID tokens; public SPA — no client secret
- `OpenSearchEndpoint`, `OpenSearchDomainArn`, index names; VPC subnet and security group IDs
- customer KMS key ARN, retention settings, OpenSearch ISM policy
- approved analysis, embedding, and optional portal chat model IDs/ARNs
- API throttles, Lambda reserved concurrency, alarm notification topic

## Authentication And Authorization

JWT mode (`PortalAuthMode=jwt`): API Gateway JWT authorizer plus Lambda
validation of issuer, audience, optional tenant (`PortalJwtTenantId` when
set), and analyst grant. Missing or invalid bearer token returns `401`. Valid
access token without configured role or scope returns `403`.

IAM mode (`PortalAuthMode=iam`): SigV4-signed API calls for automation and
operator tooling only. Analysts do not authenticate through the browser with IAM
credentials; browser sessions require JWT mode and customer IdP or `manual` /
`entra` SPA token acquisition.

Frontend `VITE_PORTAL_AUTH_MODE` controls browser token acquisition only when
backend JWT mode is enabled: `manual` stores a supplied access token,
`entra` performs interactive Entra sign-in (MSAL PKCE, no client secret),
`none` does not acquire tokens in the browser.

`/health` and `/ready` are unauthenticated; case and chat routes are never public.

Static SPA routes are unauthenticated (no customer data or credentials). Portal
role can `s3:GetObject` only for UI bucket objects; cannot list or write.

## Case And Chat Contracts

- One logical `finding_id` may have multiple immutable analysis runs.
- DynamoDB stores current pointer and run metadata; S3 stores immutable envelopes.
- OpenSearch case chunks filtered by tenant and case ID; retain S3 provenance.
- List cursors require the complete two-part cursor; malformed cursors fail closed.
- `client_request_id` is the chat idempotency key.
- Chat capacity reservation and persistence use DynamoDB transactions.
- Retrieved knowledge is advisory; must not be represented as current-alert evidence.
- Portal chat is synchronous, capped at 29 seconds (regional HTTP API limit).

## Readiness

`GET /ready` performs bounded, non-mutating probes for enabled dependencies:
DynamoDB case index and optional chat tables, S3 archive access, embed queue
configuration, signed OpenSearch cluster health when case Q&A is enabled.
Readiness fails when an enabled capability is misconfigured or unavailable.
Health remains a process liveness check.

## Deployment

1. Deploy the immutable Lambda image by ECR digest.
2. Configure customer issuer, audience, tenant, analyst grant, CORS origins, VPC,
   KMS key, OpenSearch domain, and model identifiers.
3. Build and upload the SPA — see
   [`../../../frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md).
4. Confirm API Gateway throttling, network access controls, alarms, and log retention.
5. **Negative:** unauthorized request receives `401` or `403`, never case data.
6. Verify static assets load, API routes remain authorized, path traversal rejected.
7. Run one staged case through archive, embed queue, OpenSearch retrieval, and chat.

## Failure Handling

- Analyzer and embed delivery use SQS with partial-batch failure responses and DLQs.
- Failed or pending embeddings remain visible for reconciliation.
- OpenSearch or Bedrock chat failure returns bounded service error; does not mutate case evidence.
- Duplicate chat requests return the previously committed turn (idempotent).
- DLQ redrive is explicit operator action after the cause is corrected.

## Retention And Recovery

Retention set during customer operationalization for S3, DynamoDB TTLs, logs,
queues/DLQs, and OpenSearch documents. Configure OpenSearch ISM for the four
product indexes when document expiry is required. Backup/restore and cross-region
DR are deferred internal gaps, not implemented product capabilities.

## Validation

Unit and staging commands: [`../../testing/TESTING.md`](../../testing/TESTING.md)
(portal pytest slice, frontend `npm` checks, Wave 1 / customer-default rows,
Playwright E2E via frontend README).

## Deploy path — next

- **Path B (step 11):** [`../../../frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md) — build and upload SPA
- **Path B (step 12):** [`../../testing/TESTING.md`](../../testing/TESTING.md) — customer-default staging validation

## Related Docs

- [`../deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](../deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md)
- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
