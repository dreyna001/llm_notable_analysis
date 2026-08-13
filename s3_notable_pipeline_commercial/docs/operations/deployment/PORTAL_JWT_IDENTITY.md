# Commercial AWS portal JWT identity

Configure an OIDC identity source for the analyst portal when
`PortalEnabled=true` and `PortalAuthMode=jwt` (default).

The product **validates** JWTs at API Gateway and again in the portal Lambda.
It does **not** host login pages, user directories, or token issuance.

Region: `us-east-1`. Partition: `aws`.

## What you must provide

| SAM parameter | Purpose |
| --- | --- |
| `PortalJwtIssuer` | OIDC issuer URL (HTTPS, no credentials in URL) |
| `PortalJwtAudience` | API audience (`aud`) expected on every token |
| `PortalRequiredAnalystRole` **or** `PortalRequiredAnalystScope` | Analyst grant — at least one required when portal JWT is enabled |
| `PortalCorsAllowedOrigins` | Exact browser origins allowed to call the API (e.g. `https://portal.customer.example`) |
| `RagTenantId` | Tenant id used in application checks (align with token claims if you enforce tenant in app layer) |

Optional: `PortalAuthMode=iam` for SigV4-only clients (no JWT authorizer).

## Token contract (what the product checks)

API Gateway JWT authorizer validates issuer and audience on `/api/*` routes.

Portal Lambda additionally requires:

- Valid signature via issuer JWKS (`/.well-known/openid-configuration` or `/.well-known/jwks.json`)
- Claims: `exp`, `iss`, `aud` (required)
- **`sub`** — used as portal user id for chat idempotency and audit
- **Analyst grant** — token must include configured **role** and/or **scope**:

| SAM parameter | Accepted claim names |
| --- | --- |
| `PortalRequiredAnalystRole` | `roles`, `role`, `app_role`, `application_role`, Keycloak `realm_access.roles`, nested `resource_access.*.roles` |
| `PortalRequiredAnalystScope` | `scope`, `scp`, `scopes` (space- or comma-separated string, or array) |

A valid token **without** the configured role/scope returns **403**.

Static SPA assets (`/`, `/cases`, etc.) are served **without** JWT; only `/api/*`
case and chat routes require authentication.

## Reference: Amazon Cognito user pool (common pattern)

Use when you do not already have a corporate IdP. Adapt names to your org.

1. **Create user pool** in `us-east-1` with MFA per org policy
2. **Create app client** (no client secret for public SPA + PKCE, or confidential client if your edge handles secrets)
3. **Configure hosted UI / OIDC** — note:
   - Issuer: `https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>`
   - Audience: app client id **or** resource-server identifier if using custom scopes
4. **Define analyst grant** — pick one approach:
   - **Scope:** create resource server scope e.g. `portal:analyst`; set `PortalRequiredAnalystScope=portal:analyst`
   - **Role:** map a Cognito group to a `custom:roles` or use pre-token generation Lambda to emit `roles` claim; set `PortalRequiredAnalystRole=analyst`
5. **Create test user** in the `analyst` group or assign scope
6. **Obtain token** for smoke (CLI or hosted UI redirect); decode at jwt.io locally — verify `iss`, `aud`, `sub`, role/scope
7. **Set SAM parameters** at deploy with issuer, audience, grant, and CORS origin
8. **Deploy stack**, then build/upload portal SPA to `PortalUiBucketName`

Cognito is one option; Okta, Azure AD, Keycloak, or corporate OIDC work the same
way if they expose RS256/ES256 JWKS and the claims above.

## Map claims to SAM parameters (examples)

| IdP style | `PortalJwtIssuer` | `PortalJwtAudience` | Grant |
| --- | --- | --- | --- |
| Cognito user pool | `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123` | App client id | `PortalRequiredAnalystScope=portal/read` |
| Keycloak | `https://auth.customer.example/realms/soc` | `notable-portal` | `PortalRequiredAnalystRole=analyst` |
| Okta | `https://customer.okta.com/oauth2/default` | `api://notable-portal` | `PortalRequiredAnalystScope=portal:analyst` |

Use comma-separated values for multiple allowed roles or scopes.

## Browser and CORS

`PortalCorsAllowedOrigins` must list the **exact origin** the browser uses
(scheme + host + port, no path). The portal SPA calls the regional API Gateway URL;
your edge DNS may front that URL but CORS must match the origin the browser sends.

The product does not provision CloudFront, ALB, or WAF — customer network edge is
out of scope for v1.

## Deploy order

```text
1. VPC + OpenSearch (if case Q&A / RAG) — see path B in docs/README.md
2. Choose IdP + analyst grant model (this runbook)
3. sam deploy with portal JWT parameters
4. Build/upload frontend/analyst-portal to PortalUiBucketName
5. Smoke: browser or curl with Bearer token to /api/cases
```

## Validation

1. **Without token** — `GET /api/cases` returns 401
2. **Valid token, wrong scope/role** — 403
3. **Valid analyst token** — 200 with case list JSON
4. **CORS** — browser preflight from configured origin succeeds
5. **E2E** — optional `PORTAL_E2E_JWT` smoke per [`../../testing/TESTING.md`](../../testing/TESTING.md)

Obtain a short-lived test token; do not commit tokens to git or store in SPA assets.

## IAM mode alternative

Set `PortalAuthMode=iam`. Clients sign requests with SigV4. Browser automation
requires customer tooling; JWT is the documented analyst browser path.

## Related docs

- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
- [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
