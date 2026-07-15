# Azure analyst portal operations

The browser, API, and chat share one Front Door Premium hostname. Static `$web`,
the portal Function backend, and the `$web` origin are private. Front Door sends
all API requests directly to the Function; direct origin access must fail. Every API route,
including `/health` and `/ready`, requires a valid bearer token.

## Authentication and ownership

Both portal modes validate issuer, audience, expiry, signature, `sub`, and the
configured role or delegated scope. Stable ownership is
derived only from `sub`; email, display name, and caller headers are not identity
contracts. Production is same-origin and emits no permissive CORS policy.

Register the UI as an Entra public SPA client using authorization-code + PKCE.
Set `PORTAL_OIDC_CLIENT_ID`, `PORTAL_OIDC_AUTHORITY`, and
`PORTAL_OIDC_API_SCOPE` for the build, and register the exact Front Door origin
as a redirect/logout URI. No browser client secret is used.

Before enablement, test missing, expired, wrong-issuer, wrong-audience,
missing-`sub`, and missing-role tokens. Use two valid test identities to prove
one cannot read, append to, or delete the other's chat session. Run the copied
OpenAPI contract unchanged. Browser chat timeout is 220 seconds, Function
timeout 225 seconds and Front Door origin timeout 240 seconds.

## Chat abuse and cost controls

The primary chat gate is identity-aware and stored in Cosmos DB. A single
strongly consistent document per authenticated `sub` atomically enforces two
active calls, 30 admitted calls per hour, and 100,000 reserved budget units per
hour by default. Each admitted call reserves 5,000 units. Tune that reservation
to the measured combined input/output token cost of this application's bounded
prompt; it is intentionally conservative and is not a billing-meter substitute.
All rejected calls return `429`, a stable reason, and `Retry-After`.

Clients should send a unique `client_request_id` for every intentional chat
turn and reuse it only when retrying that same turn. The gate retains IDs for
one hour, so transport retries do not consume the budget twice or execute the
model twice. Active leases expire after 300 seconds, recovering capacity after
a worker crash. Keep `PORTAL_CHAT_LEASE_SECONDS` greater than
`PORTAL_CHAT_TIMEOUT_SEC`. The process-local 18-call semaphore remains only as
a final worker-capacity guard; it is not a distributed quota.

Quota storage must be a dedicated Cosmos container partitioned by `/user_id`,
with item TTL enabled, and the portal managed identity must have Cosmos DB
Built-in Data Contributor scoped to that container. Admission control fails
closed with `503` if Cosmos is unavailable. Disabling
`PORTAL_CHAT_DISTRIBUTED_QUOTA_ENABLED` is a rollback/emergency capability, not
the normal production profile.

Front Door WAF IP rate limiting is optional edge flood protection, not the
primary cost control. Azure Front Door rate-limit custom rules group callers by
source IP; corporate proxies and VPNs can place many analysts behind one NAT
address. Therefore this stack does not enable an opinionated rule by default.
If traffic evidence justifies it, add a WAF custom `RateLimitRule` scoped to
`/api/chat`, start in Log mode, select a threshold comfortably above legitimate
aggregate NAT traffic, review logs, then move to Block. Do not treat forwarded
identity headers as trusted quota keys; authenticated `sub` remains the
application quota identity.

The quota document retains request IDs only for the configured dedupe interval.
Startup rejects settings whose worst-case overlap of fixed rate windows could
retain more than 4,096 IDs, keeping the document comfortably below Cosmos DB's
2 MB item limit even when every client request ID uses all 128 allowed
characters. `PORTAL_CHAT_MAX_REQUESTS_PER_WINDOW` is additionally capped at
2,048. Reduce the dedupe interval or increase the quota-window duration before
raising the request rate; do not bypass this validation.

## Authenticated synthetic monitor

The customer owns a dedicated non-human identity with only the portal read role.
Its monitor obtains a short-lived token through the approved IdP flow and sends:

```http
GET https://<front-door-host>/ready
Authorization: Bearer <short-lived-token>
```

Expected status is `200` with the published readiness response. When distributed
admission is enabled, readiness reads the quota container metadata and reports
`chat_admission: unavailable` with `503` if the container is missing or its RBAC
grant is ineffective. Alert after the customer-approved consecutive-failure
threshold. Record monitor location,
identity object ID, token issuance method, renewal/rotation owner, action group,
and escalation route. The stack does not store a browser token or IdP client
credential. Front Door origin probes remain disabled because they cannot
authenticate.

## Operations and recovery

Monitor Front Door 5xx, portal Function failures/timeouts, Cosmos 429s,
OpenAI errors, synthetic failure, and chat context/latency. A failed `/ready`
requires checking Front Door private-link approval, Function public-network state,
Function health, identity/RBAC, Cosmos, Search, and OpenAI—not bypassing the
edge.

Alert on sustained quota-backend failures and unexpected denial growth. The
Function emits `chat_quota_decision` with custom dimensions
`chat_quota_outcome`, `chat_quota_user_hash`, and `chat_quota_request_id`. The user identity is hashed
before logging; request IDs should still follow restricted portal telemetry
policy. A starting Application Insights query is:

```kusto
traces
| where message startswith "chat_quota_decision"
| summarize requests=count() by tostring(customDimensions.chat_quota_outcome), bin(timestamp, 5m)
```

Deploy UI and API together when their contract changes. Roll back to the last
qualified UI artifact plus immutable Function image digest. Never make Function,
Function, or `$web` public to recover service. If the synthetic credential
fails, rotate it through the customer IdP and prove an analyst identity still
works before classifying the event as application downtime.

See [`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md)
and [`../AZURE_MONITORING_AND_RECOVERY.md`](../AZURE_MONITORING_AND_RECOVERY.md).
