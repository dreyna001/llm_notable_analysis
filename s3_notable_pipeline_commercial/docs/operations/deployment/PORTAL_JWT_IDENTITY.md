# Commercial AWS portal JWT identity

Configure an OIDC identity source for the analyst portal when
`PortalEnabled=true` and `PortalAuthMode=jwt` (default). The product **validates**
JWTs at API Gateway and again in the portal Lambda — it does **not** host login
pages, user directories, or token issuance.

Partition `aws`, region `us-east-1` — see
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md#deployment-boundary).

**Path B step 5** (before SAM when portal JWT mode is enabled):
[`../../../README.md`](../../../README.md#path-b-customer-default).

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

1. **Create user pool** in `us-east-1` with MFA per org policy; create app client (PKCE for public SPA)
2. **Note issuer and audience** — issuer: `https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>`; audience: app client id or resource-server identifier
3. **Define analyst grant** — scope (e.g. `portal:analyst` -> `PortalRequiredAnalystScope`) or role via group/`custom:roles` -> `PortalRequiredAnalystRole`
4. **Create test user**, obtain token, verify `iss`, `aud`, `sub`, role/scope
5. **Set SAM parameters** at deploy; after deploy build/upload portal SPA to `PortalUiBucketName`

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

## Next

- **Path B step 6:** [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- **Path C:** same when `analyst_portal` is in the profile set — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- Day-two portal ops: [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
