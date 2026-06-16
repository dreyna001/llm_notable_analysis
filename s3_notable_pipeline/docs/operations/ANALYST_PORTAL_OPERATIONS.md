# Analyst Portal Operations

This guide covers the AWS read-only analyst portal, S3 case archive, DynamoDB
CaseIndex, post-archive embedding, pinned-case Q&A, and static React SPA.

## What This Controls

The `analyst_portal` capability archives analyzed cases, indexes case metadata
in DynamoDB, stores retrieval chunks in S3, serves a read-only Lambda portal API,
and enables selected-case Q&A over retained chunks.

Portal routes do not mutate cases, run SPL or Elasticsearch, create tickets,
call SOAR, or trigger remediation. `POST /api/chat` is a query transport only
and requires `selected_case_id`.

## Recommended Starting Posture

- Enable the portal first in a non-production account with
  `CapabilityProfiles=core,analyst_portal`.
- Keep `PortalAuthMode=jwt`; configure `PortalJwtIssuer` and
  `PortalJwtAudience` for the customer identity provider.
- Set `PortalCorsAllowedOrigins` to the exact CloudFront or approved browser
  origin. Do not use broad wildcard origins for JWT-bearing browser requests.
- Keep `PortalChatMaxConcurrency=18` and `PortalChatTimeoutSec=300` until
  Bedrock latency and analyst concurrency are measured.
- Keep `CaseRetentionDays=30` until the customer confirms evidence retention,
  privacy, and storage requirements.

## Customer Decisions

Operators must decide:

- Which AWS account and region host the archive, API, and static SPA.
- Which identity provider issues portal JWTs, and which audience claim is used.
- The public portal origin that will be allowed by CORS.
- The CloudFront/S3 static hosting pattern and whether a separate WAF,
  corporate IdP front door, or private network path is required.
- The case retention window and whether archived reports are exported before
  lifecycle deletion.
- Whether chat history remains disabled or is enabled later with the dedicated
  DynamoDB tables.

## Portal API Front Door (Stack-Managed)

When `CaseIndexTableName` is set (required for `analyst_portal`), the
SAM/CloudFormation templates automatically create:

| Resource | When created | Purpose |
| --- | --- | --- |
| **API Gateway HTTP API** | Always with portal resources | Read routes, health/ready, and chat when Function URL is disabled |
| **Lambda Function URL** | `PortalChatFunctionUrlEnabled=true` (default) | Long-running `POST /api/chat` up to `PortalChatTimeoutSec` |
| **CloudFront API behaviors** | `PortalUiBucketName` is set | Same-origin SPA: UI from S3, `/api/*` to API Gateway, `/api/chat` to Function URL |

Stack outputs (copy after deploy):

| Output | Use |
| --- | --- |
| `PortalBrowserApiBaseUrl` | **Recommended SPA API base.** CloudFront hostname when UI is deployed; otherwise Function URL or API Gateway URL. |
| `PortalApiUrl` | Direct API Gateway invoke URL for read routes and tooling. |
| `PortalChatFunctionUrl` | Direct Function URL when chat is split from CloudFront or API-only deploys. |
| `PortalUiDistributionDomainName` | Browser origin for the static SPA when UI hosting is enabled. |

### Per-customer deploy checklist

1. Set portal parameters before deploy:
   - `CapabilityProfiles=core,analyst_portal`
   - `PortalJwtIssuer` and `PortalJwtAudience` matching the customer IdP
   - `PortalCorsAllowedOrigins` set only when the SPA and API are on different
     browser origins
   - `PortalUiBucketName` when the stack should host the static SPA
   - `PortalChatFunctionUrlEnabled=true` (default) for chat longer than API Gateway's 30s integration limit
2. Deploy the stack and record outputs: `PortalBrowserApiBaseUrl`,
   `PortalUiDistributionDomainName` (when UI enabled), `PortalApiUrl`,
   `PortalChatFunctionUrl` (when enabled).
3. Set `PortalCorsAllowedOrigins` to the SPA origin only for split-origin
   browser calls:
   - **CloudFront UI with same-origin API behaviors:** leave blank unless a
     separate browser host will call the API directly.
   - **External static host:** that host's exact HTTPS origin.
4. Build and upload the SPA:
   - **CloudFront UI with API behaviors (recommended):** leave
     `VITE_PORTAL_API_BASE_URL` unset; the SPA uses same-origin relative paths.
   - **Split UI and API hostnames:** set
     `VITE_PORTAL_API_BASE_URL=<PortalBrowserApiBaseUrl>` (no trailing slash).
5. Issue browser JWTs from the customer IdP with matching `iss` and `aud`.
   Store the token in the browser under `notable.portal.jwt` (session or local
   storage) before opening protected routes.
6. Validate from the browser: `/health`, case list/detail, and cited chat on a
   pinned case.

JWT validation posture:

- **API Gateway routes:** HTTP API JWT authorizer when `PortalAuthMode=jwt` and
  issuer/audience parameters are set. Lambda also validates claims on every
  protected route.
- **Function URL routes:** for `PortalAuthMode=jwt`, Lambda validates
  `Authorization: Bearer` tokens against the issuer JWKS (`portal_jwt.py`).
  Required because Function URL has no edge JWT authorizer. For
  `PortalAuthMode=iam`, the Function URL uses `AWS_IAM` auth instead.

Customer-specific items that remain outside the stack:

| Item | Notes |
| --- | --- |
| Custom DNS / ACM certificate | Optional alias on CloudFront or API Gateway |
| WAF, IP allowlists, private networking | Corporate access controls in front of CloudFront or API Gateway |
| IdP app registration | Client, audience, and token issuance for analysts |
| Chat history tables | Only when `CaseQaChatHistoryEnabled=true` |

### Deploy patterns

**Pattern A — single CloudFront origin (recommended when UI is in-stack):**

```text
Browser -> CloudFront (PortalUiDistributionDomainName)
  /, /assets/*           -> S3 portal UI bucket
  /health, /ready, /api/* -> API Gateway (JWT authorizer at edge)
  /api/chat              -> Lambda Function URL (when enabled)
```

Build SPA without `VITE_PORTAL_API_BASE_URL`. `PortalCorsAllowedOrigins` can stay
blank because browser requests are same-origin at the CloudFront hostname.

**Pattern B — API-only or external UI host:**

```text
Browser -> VITE_PORTAL_API_BASE_URL=<PortalChatFunctionUrl or PortalApiUrl>
```

Prefer `PortalChatFunctionUrl` when chat is enabled so requests honor
`PortalChatTimeoutSec`. Set `PortalCorsAllowedOrigins` to the SPA origin.

**Pattern C — custom domain / corporate reverse proxy:**

Point the customer hostname at CloudFront or terminate TLS on a reverse proxy that
forwards `/api/chat` to `PortalChatFunctionUrl` and other API paths to
`PortalApiUrl`. Keep JWT issuer, audience, and CORS aligned with the browser
origin analysts actually use.

## Config Quick Reference

Primary SAM/CloudFormation parameters:

| Parameter | Purpose |
| --- | --- |
| `CapabilityProfiles` | Include `analyst_portal` to enable archive, portal API, and case Q&A. |
| `CaseArchiveBucketName` | S3 bucket for case envelopes and chunks. |
| `CaseIndexTableName` | DynamoDB CaseIndex table name. |
| `CaseRetentionDays` | Retention window for S3 lifecycle and DynamoDB TTL. |
| `CaseEmbedLambdaName` | Async embed Lambda invoked after archive writes. |
| `PortalApiLambdaName` | Portal API Lambda function name. |
| `PortalAuthMode` | `jwt` or `iam`; browser SPA path expects `jwt`. |
| `PortalJwtIssuer` | Required JWT issuer for portal auth. |
| `PortalJwtAudience` | Required JWT audience for portal auth. |
| `PortalCorsAllowedOrigins` | Comma-separated browser origins allowed to call the API. |
| `PortalChatTimeoutSec` | Lambda timeout for chat synthesis. |
| `PortalChatFunctionUrlEnabled` | Creates Lambda Function URL for long chat (default `true`). |
| `PortalChatMaxConcurrency` | In-handler chat concurrency cap per Lambda execution environment. |
| `PortalUiBucketName` | Optional S3 bucket for static SPA; enables CloudFront UI plus API routing behaviors. |
| `PortalChatBedrockModelId` | Optional answer synthesis model override. |

The React SPA reads `VITE_PORTAL_API_BASE_URL` at build/runtime through Vite and
uses same-origin requests when it is unset. It sends `Authorization: Bearer ...`
when the browser has a token under `notable.portal.jwt` in session storage or
local storage.

## Static SPA Deployment

Build the vendored UI from the repository root:

```powershell
npm --prefix s3_notable_pipeline/frontend/analyst-portal install
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
```

For a separate API origin:

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<portal-api-origin>"
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
```

Deploy `s3_notable_pipeline/frontend/analyst-portal/dist` to the approved static
hosting bucket and configure SPA fallback to `/index.html`. Put CloudFront in
front of the bucket, keep S3 public access blocked, and use an origin access
control or equivalent private origin pattern.

The API origin must include the SPA origin in `PortalCorsAllowedOrigins`; otherwise
the browser will fail preflight or omit responses even when the JWT is valid.

## Auth And Failure Behavior

- `GET /health` and `GET /ready` are unauthenticated probes.
- All `/api/*` routes require JWT claims matching `PortalJwtIssuer` and
  `PortalJwtAudience` when `PortalAuthMode=jwt`.
- Mutating methods are rejected. Only `GET` and `POST /api/chat` are allowed.
- Chat requires a selected case and returns `insufficient_context` when chunks
  are unavailable, the case is not retrieval-ready, or model output is malformed
  or uncited.
- `POST /api/chat` returns `429` when the per-environment semaphore is saturated.

## Retention And Lifecycle

Case envelopes and chunks live in the archive bucket under the configured archive
prefixes. DynamoDB CaseIndex items use `expires_at` for TTL. S3 lifecycle rules
and DynamoDB TTL should both match `CaseRetentionDays`; lowering retention can
delete evidence needed by analysts, so export reports first when longer audit
retention is required.

For the full on-prem vs AWS retention mapping, see
[`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md#retention-equivalence-on-prem-vs-aws).

## Validation And Rollout

Local verification must not call real AWS:

```powershell
python -m unittest discover -s s3_notable_pipeline/tests -p "test_*.py" -v
npm --prefix s3_notable_pipeline/frontend/analyst-portal test
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
```

Optional dev/staging/prod validation only:

1. Deploy with `CapabilityProfiles=core,analyst_portal`.
2. Upload a representative notable under `incoming/`.
3. Confirm case envelope and chunk objects are written to the archive bucket.
4. Confirm the CaseIndex item has `retrieval_status=ready`.
5. Open the SPA through the approved origin with a valid JWT.
6. Confirm `/`, `/cases`, and `/cases/{case_id}` load.
7. Ask a selected-case question and confirm the answer includes citations.
8. Review CloudWatch logs for bounded errors without secrets or raw tokens.

## Rollback

- Remove `analyst_portal` from `CapabilityProfiles` and redeploy to disable new
  archive, portal, and Q&A behavior.
- Disable the static SPA distribution or route users away from the CloudFront
  origin if the API must remain deployed for operator validation.
- Existing S3 archive objects and DynamoDB rows are not deleted immediately by
  disabling the profile; lifecycle and TTL continue according to configured
  retention.

## Related Docs

- [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md)
- [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
- [`../testing/TESTING.md`](../testing/TESTING.md)
