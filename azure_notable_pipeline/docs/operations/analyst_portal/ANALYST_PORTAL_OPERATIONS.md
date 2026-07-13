# Azure analyst portal operations

The browser, API, and chat share one Front Door Premium hostname. Static `$web`,
APIM Standard v2, and the portal Function origin are private. Direct origin
access must fail. Every API route, including `/health` and `/ready`, requires a
valid bearer token.

## Authentication and ownership

`PORTAL_AUTH_MODE=jwt` validates issuer, audience, expiry, signature, and `sub`.
`iam` additionally requires the configured Entra app role. Stable ownership is
derived only from `sub`; email, display name, and caller headers are not identity
contracts. Production is same-origin and emits no permissive CORS policy.

Before enablement, test missing, expired, wrong-issuer, wrong-audience,
missing-`sub`, and missing-role tokens. Use two valid test identities to prove
one cannot read, append to, or delete the other's chat session. Run the copied
OpenAPI contract unchanged. Browser chat timeout is 220 seconds, Function
timeout 225 seconds, and Front Door origin timeout 240 seconds.

## Authenticated synthetic monitor

The customer owns a dedicated non-human identity with only the portal read role.
Its monitor obtains a short-lived token through the approved IdP flow and sends:

```http
GET https://<front-door-host>/ready
Authorization: Bearer <short-lived-token>
```

Expected status is `200` with the published readiness response. Alert after the
customer-approved consecutive-failure threshold. Record monitor location,
identity object ID, token issuance method, renewal/rotation owner, action group,
and escalation route. The stack does not store a browser token or IdP client
credential. Front Door origin probes remain disabled because they cannot
authenticate.

## Operations and recovery

Monitor Front Door/APIM 5xx, portal Function failures/timeouts, Cosmos 429s,
OpenAI errors, synthetic failure, and chat context/latency. A failed `/ready`
requires checking Front Door private-link approval, APIM public-network state,
Function health, identity/RBAC, Cosmos, Search, and OpenAI—not bypassing the
edge.

Deploy UI and API together when their contract changes. Roll back to the last
qualified UI artifact plus immutable Function image digest. Never make APIM,
Function, or `$web` public to recover service. If the synthetic credential
fails, rotate it through the customer IdP and prove an analyst identity still
works before classifying the event as application downtime.

See [`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md)
and [`../AZURE_MONITORING_AND_RECOVERY.md`](../AZURE_MONITORING_AND_RECOVERY.md).
