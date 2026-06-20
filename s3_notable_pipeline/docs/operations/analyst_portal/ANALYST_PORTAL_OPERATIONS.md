# Analyst Portal Operations

This guide covers the AWS read-only analyst portal, S3 case archive, DynamoDB
CaseIndex, post-archive embedding Lambda, pinned-case Q&A, and static React SPA.

## What This Controls

The `analyst_portal` capability archives analyzed cases, indexes case metadata
in DynamoDB, stores retrieval chunks in S3, serves a read-only portal Lambda API,
and enables selected-case Q&A over retained chunks.

Portal routes do not mutate cases, run SPL or Elasticsearch, create tickets,
call SOAR, or trigger remediation. `POST /api/chat` is query transport only
and requires `selected_case_id`. When `CaseQaChatHistoryEnabled=true`, chat
session routes write scoped rows to the dedicated DynamoDB chat tables only.

## Recommended Starting Posture

- Enable the portal first in a non-production account with
  `CapabilityProfiles=core,analyst_portal`.
- Set a non-empty `CaseIndexTableName` so the stack creates CaseIndex, portal
  API, and optional UI resources.
- Keep `PortalAuthMode=jwt`; configure `PortalJwtIssuer` and
  `PortalJwtAudience` for the customer identity provider.
- Set `PortalCorsAllowedOrigins` to the exact CloudFront or approved browser
  origin. Do not use broad wildcard origins for JWT-bearing browser requests.
- Keep `PortalChatMaxConcurrency=18` and `PortalChatTimeoutSec=300` until
  Bedrock latency and analyst concurrency are measured.
- Keep `PortalChatFunctionUrlEnabled=true` (default) so chat can exceed API
  Gateway's 30-second integration limit.
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
- Whether chat history remains disabled or is enabled later with
  `CaseQaChatHistoryEnabled=true` and the chat DynamoDB tables.

## Enable And Disable

The `analyst_portal` profile sets `CASE_ARCHIVE_ENABLED`, `PORTAL_ENABLED`, and
`CASE_QA_ENABLED`. It does not enable `HTML_REPORT_ENABLED` or
`CASE_QA_CHAT_HISTORY_ENABLED`.

Rollback options:

- Remove `analyst_portal` from `CapabilityProfiles` and redeploy to disable new
  archive, portal, and Q&A behavior on the analyzer and portal Lambdas.
- Disable the CloudFront distribution or route analysts away from the portal
  origin if the API must remain deployed for operator validation.
- Existing S3 archive objects and DynamoDB rows are not deleted immediately by
  disabling the profile; lifecycle and TTL continue according to configured
  retention.

## Case Archive Ingest

After each completed analysis, the analyzer Lambda calls `archive_case`:

1. Resolve a stable `finding_id` from alert identifiers or the input object key
   stem, then derive `case_id`.
2. Write the canonical case envelope to S3 under `CaseArchivePrefix` (default
   `cases/`) in `CaseArchiveBucketName` (defaults to the output bucket when
   blank).
3. Upsert the CaseIndex row in DynamoDB with `expires_at` aligned to
   `CaseRetentionDays`.
4. When `CASE_QA_ENABLED` is true, set `retrieval_status=pending` and invoke the
   async embed Lambda (`CaseEmbedLambdaName`, default `notable-case-embed`).
5. The embed Lambda writes chunk objects under `CaseArchiveChunksPrefix`
   (default `case_chunks/`) and sets `retrieval_status=ready` or `failed`.

Archive write failures are logged and suppressed by default
(`CaseArchiveFailureMode=suppress`) so ingest continues. Chunk failures leave
`retrieval_status=failed` until an operator reprocesses the case.

## Portal API Front Door (Stack-Managed)

When `CaseIndexTableName` is non-empty, the SAM/CloudFormation templates create
Wave 2 portal resources. Runtime `analyst_portal` validation also requires
`CaseIndexTableName`, JWT issuer/audience when `PortalAuthMode=jwt`, and
`CaseEmbedLambdaName` when Case Q&A is enabled.

| Resource | When created | Purpose |
| --- | --- | --- |
| **API Gateway HTTP API** | `CaseIndexTableName` is set | Read routes, health/ready, and chat when Function URL is disabled |
| **Lambda Function URL** | `PortalChatFunctionUrlEnabled=true` (default) | Long-running `POST /api/chat` up to `PortalChatTimeoutSec` |
| **CloudFront distribution** | `PortalUiBucketName` is set | Same-origin SPA: UI from S3, `/api/*` to API Gateway, `/api/chat` to Function URL |

Stack outputs (copy after deploy):

| Output | Use |
| --- | --- |
| `PortalBrowserApiBaseUrl` | **Recommended SPA API base.** CloudFront hostname when UI is deployed; otherwise Function URL or API Gateway URL. |
| `PortalApiUrl` | Direct API Gateway invoke URL for read routes and tooling. |
| `PortalChatFunctionUrl` | Direct Function URL when chat is split from CloudFront or API-only deploys. |
| `PortalUiDistributionDomainName` | Browser origin for the static SPA when UI hosting is enabled. |
| `PortalUiBucketName` | S3 bucket for the built SPA when stack UI hosting is enabled. |

### Per-customer deploy checklist

1. Set portal parameters before deploy:
   - `CapabilityProfiles=core,analyst_portal`
   - Non-empty `CaseIndexTableName`
   - `PortalJwtIssuer` and `PortalJwtAudience` matching the customer IdP
   - `PortalCorsAllowedOrigins` set only when the SPA and API are on different
     browser origins
   - `PortalUiBucketName` when the stack should host the static SPA
   - `PortalChatFunctionUrlEnabled=true` (default) for chat longer than API
     Gateway's 30s integration limit
2. Deploy the stack and record outputs: `PortalBrowserApiBaseUrl`,
   `PortalUiDistributionDomainName` and `PortalUiBucketName` (when UI enabled),
   `PortalApiUrl`, `PortalChatFunctionUrl` (when enabled).
3. Set `PortalCorsAllowedOrigins` to the SPA origin only for split-origin
   browser calls:
   - **CloudFront UI with same-origin API behaviors:** leave blank unless a
     separate browser host will call the API directly.
   - **External static host:** that host's exact HTTPS origin.
4. Build and upload the SPA:
   - **CloudFront UI with API behaviors (recommended):** leave
     `VITE_PORTAL_API_BASE_URL` unset; sync `dist/` to `PortalUiBucketName`.
   - **Split UI and API hostnames:** set
     `VITE_PORTAL_API_BASE_URL=<PortalBrowserApiBaseUrl>` (no trailing slash).
5. Issue browser JWTs from the customer IdP with matching `iss` and `aud`.
   Store the token in the browser under `notable.portal.jwt` (session or local
   storage) before opening protected routes.
6. Validate from the browser: `/health`, `/ready`, case list/detail, and selected-case
   chat with a bounded `answer_status`.

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
  /health, /ready        -> API Gateway (unauthenticated routes)
  /api/* (except chat)   -> API Gateway (JWT authorizer at edge when configured)
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
| `CaseArchiveBucketName` | S3 bucket for case envelopes and chunks (defaults to output bucket). |
| `CaseArchivePrefix` | S3 prefix for case envelopes (default `cases`). |
| `CaseArchiveChunksPrefix` | S3 prefix for embedded chunks (default `case_chunks`). |
| `CaseIndexTableName` | DynamoDB CaseIndex table name; non-empty value creates portal stack resources. |
| `CaseRetentionDays` | Retention window for S3 lifecycle and DynamoDB TTL. |
| `CaseEmbedLambdaName` | Async embed Lambda invoked after archive writes. |
| `PortalApiLambdaName` | Portal API Lambda function name. |
| `PortalAuthMode` | `jwt` or `iam`; browser SPA path expects `jwt`. |
| `PortalJwtIssuer` | Required JWT issuer for portal auth. |
| `PortalJwtAudience` | Required JWT audience for portal auth. |
| `PortalCorsAllowedOrigins` | Comma-separated browser origins allowed to call the API. |
| `PortalPageSize` | Default case list page size (max 100). |
| `PortalChatTimeoutSec` | Lambda timeout for chat synthesis. |
| `PortalChatFunctionUrlEnabled` | Creates Lambda Function URL for long chat (default `true`). |
| `PortalChatMaxConcurrency` | In-handler chat concurrency cap per Lambda execution environment. |
| `PortalUiBucketName` | Optional S3 bucket for static SPA; enables CloudFront UI plus API routing behaviors. |
| `PortalChatBedrockModelId` | Optional answer synthesis model override. |
| `CaseQaGeneralKnowledgeEnabled` | Advisory general-knowledge fallback when case retrieval is weak. |
| `CaseQaChatHistoryEnabled` | Enables DynamoDB-backed chat session persistence (default `false`). |
| `ChatSessionsTableName` | Chat sessions table when history is enabled. |
| `ChatMessagesTableName` | Chat messages table when history is enabled. |
| `CaseQaChatHistoryRetentionDays` | TTL window for persisted chat history. |

The React SPA reads `VITE_PORTAL_API_BASE_URL` at build time through Vite and
uses same-origin requests when it is unset. It sends `Authorization: Bearer ...`
when the browser has a token under `notable.portal.jwt` in session storage or
local storage.

## Portal API Surface (React SPA)

Protected routes require a valid JWT when `PortalAuthMode=jwt`. `/health` and
`/ready` are unauthenticated.

| Route | Method | Purpose |
| --- | --- | --- |
| `/api/capabilities` | GET | Feature flags, limits, retention window, live `chat_ready` |
| `/api/cases` | GET | Paginated case list (`limit`, opaque `cursor`) |
| `/api/cases/{case_id}` | GET | Bounded case detail view |
| `/api/cases/{case_id}/raw/{section}` | GET | Paginated raw `alert_payload` or `analysis` JSON |
| `/api/chat` | POST | Case Q&A synthesis (`mode=selected_case`, `selected_case_id`) |
| `/api/chat/sessions` | GET | List saved chat sessions when history enabled |
| `/api/chat/sessions/{id}/messages` | GET | Load session transcript |
| `/api/chat/sessions/{id}` | DELETE | Delete a saved session |
| `/api/chat/sessions/{id}/turns/last` | DELETE | Remove last turn after Stop/cancel cleanup |
| `/api/diagnostics/chat-readiness` | GET | Embedding target, CaseIndex, and Bedrock readiness |

`GET /api/capabilities` exposes `case_qa_enabled`, `chat_history_enabled`,
`general_knowledge_enabled`, `max_question_chars`, `max_answer_tokens`,
`max_chat_sessions_per_user`, `case_retention_days`, `chat_ready`,
`chat_dependency_status`, and `chat_degraded_reason`.

OpenAPI contract: [`../../contracts/portal.openapi.json`](../../contracts/portal.openapi.json).

## Health Checks

`GET /health` is the liveness check. `GET /ready` confirms portal enablement and
that `CASE_INDEX_TABLE` is configured. It does not exercise embedding or Bedrock.

Threat model for unauthenticated probes:

- `/health` and `/ready` bypass JWT middleware so load balancers and operators can
  probe through API Gateway or CloudFront.
- `/health` returns only `{"status":"ok"}`. Operator metadata such as
  `case_retention_days`, `chat_ready`, and optional `chat_degraded_reason` are
  exposed on authenticated `GET /api/capabilities`.
- Chat retrieval readiness is intentionally separated from load balancer probes.
  Validate embedding, archive retrieval, and Bedrock with authenticated
  `GET /api/diagnostics/chat-readiness`, then validate synthesis with a sample
  authenticated `POST /api/chat` after deployment.

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

Deploy `s3_notable_pipeline/frontend/analyst-portal/dist` to the stack UI bucket
(`PortalUiBucketName`) or another approved static host. Configure SPA fallback
to `/index.html`. When using stack-managed hosting, CloudFront sits in front of
the bucket with public access blocked and origin access control on the S3 origin.

The API origin must include the SPA origin in `PortalCorsAllowedOrigins` when UI
and API are on different hostnames; otherwise the browser will fail preflight or
omit responses even when the JWT is valid.

## Auth And Failure Behavior

- `GET /health` and `GET /ready` are unauthenticated probes.
- All other `/api/*` routes require JWT claims matching `PortalJwtIssuer` and
  `PortalJwtAudience` when `PortalAuthMode=jwt`.
- Case evidence routes are read-only. Allowed methods are `GET`, `POST /api/chat`,
  and `DELETE` on `/api/chat/sessions/*` when chat history is enabled.
- Chat requires a selected case and returns `answer_status=unknown` when chunks
  are unavailable, retrieval is not ready, or synthesis cannot ground an answer.
- Cross-boundary or action-like answers return `answer_status=refused`.
- `POST /api/chat` returns `429` when the per-environment semaphore is saturated.

## Chatbot Behavior

Portal chat requires a pinned case (`selected_case_id`). Supported mode:

- `selected_case`

General technology / TTP questions can still work via `CaseQaGeneralKnowledgeEnabled`
and optional advisory knowledge-base context when enabled. Cross-case archive
search is not supported.

The portal chat path has no live Splunk, ServiceNow, SOAR, or remediation
integrations. Chat responses return synthesized `answer` and `answer_status` only;
source citations are not exposed in the API or UI (retrieval is internal to
synthesis). For threat model and non-execution guarantees, see
[`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md).

## Retention And Lifecycle

Case envelopes and chunks live in the archive bucket under the configured archive
prefixes. DynamoDB CaseIndex items use TTL on `expires_at`. S3 lifecycle rules
and DynamoDB TTL should both match `CaseRetentionDays`; lowering retention can
delete evidence needed by analysts, so export reports first when longer audit
retention is required.

For the full on-prem vs AWS retention mapping, see
[`../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md#retention-equivalence-on-prem-vs-aws).

## Validation And Rollout

Local verification must not call real AWS:

```powershell
python -m unittest discover -s s3_notable_pipeline/tests -p "test_*.py" -v
npm --prefix s3_notable_pipeline/frontend/analyst-portal test
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
```

Optional dev/staging/prod validation only:

1. Deploy with `CapabilityProfiles=core,analyst_portal` and non-empty
   `CaseIndexTableName`.
2. Upload a representative notable under `incoming/`.
3. Confirm case envelope and chunk objects are written to the archive bucket.
4. Confirm the CaseIndex item has `retrieval_status=ready`.
5. Open the SPA through the approved origin with a valid JWT.
6. Confirm `/`, `/cases`, and `/cases/{case_id}` load.
7. Ask a selected-case question and confirm a bounded `answer_status` (typically
   `answered`, `unknown`, or `refused`).
8. Review CloudWatch logs for bounded errors without secrets or raw tokens.

## Related Docs

- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
- [`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md)
- [`../../testing/TESTING.md`](../../testing/TESTING.md)
