# Commercial AWS portal JWT identity

Configure customer-owned identity for the analyst portal when
`PortalEnabled=true`. The product **validates** bearer tokens at API Gateway and
again in the portal Lambda — it does **not** host login pages, user directories,
or token issuance.

Partition `aws`, region `us-east-1` — see
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md#deployment-boundary).

**Path B step 5** (before SAM when portal JWT mode is enabled):
[`../../../README.md`](../../../README.md#path-b-customer-default).

## Two configuration layers

**Backend (`PortalAuthMode`)** — how API Gateway and the portal Lambda accept
API calls.

| Mode | Use |
| --- | --- |
| `jwt` (default) | Generic OIDC access tokens via API Gateway JWT authorizer plus Lambda claim checks. Required for analyst browser use. |
| `iam` | SigV4-signed API calls only. For automation, synthetic monitors, and operator tooling — **not** analyst browser sessions. |

**Frontend (`VITE_PORTAL_AUTH_MODE`, baked at SPA build)** — how the browser
acquires a JWT for `Authorization: Bearer` when backend mode is `jwt`:

| Mode | Use |
| --- | --- |
| `manual` (default) | Backward compatible. Analyst or operator supplies a short-lived access token (devtools, approved script, or corporate front door). Token stored under `notable.portal.jwt`. |
| `entra` | Production interactive Microsoft Entra sign-in via MSAL browser PKCE (public SPA client, no client secret). |
| `none` | No browser token acquisition or authorization header. Intended for unauthenticated local/proxy scenarios, not a protected production portal. |

Align backend and frontend: production analyst browsers need `PortalAuthMode=jwt`
with `VITE_PORTAL_AUTH_MODE=entra` or `manual`. `PortalAuthMode=iam` is never a
browser analyst path.

## What you must provide (JWT backend mode)

| SAM parameter | Purpose |
| --- | --- |
| `PortalJwtIssuer` | OIDC issuer URL (HTTPS, no credentials in URL) |
| `PortalJwtAudience` | API audience (`aud`) expected on every access token |
| `PortalRequiredAnalystRole` **or** `PortalRequiredAnalystScope` | Analyst grant — at least one required when portal JWT is enabled |
| `PortalCorsAllowedOrigins` | Exact browser origins allowed to call the API (e.g. `https://portal.customer.example`) |
| `RagTenantId` | Tenant id used in application checks (align with token claims when tenant enforcement is enabled) |

Optional: `PortalJwtTenantId` — when set, portal Lambda rejects access tokens
whose Entra `tid` claim does not match. Use the
same Entra directory tenant id you register in the SPA build.

`PortalAuthMode=iam` omits the JWT authorizer. Clients sign with SigV4; no
browser PKCE or MSAL path applies.

## Microsoft Entra (common production pattern)

Customer-owned Entra app registrations and conditional access — not provisioned by
this product.

**API application (resource)**

- Expose a delegated API scope (e.g. `api://<api-app-client-id>/portal.analyst`).
- Set `PortalJwtAudience` to the API app client id or the configured application
  id URI that appears as `aud` on issued **access tokens**.
- Optional app role for analysts — map to `PortalRequiredAnalystRole` when role
  enforcement is preferred over scope-only grants.

**SPA application (public client)**

- Platform: single-page application; authentication: MSAL browser PKCE.
- No client secret — public SPA clients must not use shared secrets.
- Register the exact sign-in and post-logout redirect URI matching the portal
  browser origin, plus `<portal-origin>/auth/silent.html` for silent token
  renewal.
- Grant delegated permission to the API scope above.

**Issuer and tenant**

- `PortalJwtIssuer`: `https://login.microsoftonline.com/<tenant-id>/v2.0`
- Entra directory tenant id: same value for `PortalJwtTenantId`
  and SPA build input `VITE_PORTAL_ENTRA_TENANT_ID`.

**SPA build inputs (`VITE_PORTAL_AUTH_MODE=entra`)**

| Build variable | Customer value |
| --- | --- |
| `VITE_PORTAL_ENTRA_TENANT_ID` | Entra directory tenant id |
| `VITE_PORTAL_ENTRA_CLIENT_ID` | SPA (public) client id |
| `VITE_PORTAL_ENTRA_API_SCOPE` | Delegated API scope (e.g. `api://<api-app-client-id>/portal.analyst`) |
| `VITE_PORTAL_ENTRA_REDIRECT_URI` | Exact sign-in redirect URI registered on the SPA app |
| `VITE_PORTAL_ENTRA_POST_LOGOUT_URI` | Exact logout redirect URI registered on the SPA app |

`PortalCorsAllowedOrigins` must include the portal origin those URIs use. When UI
and API share one regional hostname, leave `VITE_PORTAL_API_BASE_URL` unset at
build — see
[`../../../frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md).

Use the **access token** returned for the API scope, not the Entra ID token.
ID tokens use a different audience and must not be sent to `/api/*`.
Register the derived `<portal-origin>/auth/silent.html` redirect URI in Entra;
the build includes that minimal page and uses it only for silent token renewal.

## Token contract (what the product checks)

API Gateway JWT authorizer validates issuer and audience on `/api/*` routes.

Portal Lambda additionally requires:

- Valid signature via issuer JWKS (`/.well-known/openid-configuration` or `/.well-known/jwks.json`)
- Claims: `exp`, `iss`, `aud` (required)
- **`sub`** — portal user id for chat idempotency and audit
- **Analyst grant** — token must include configured **role** and/or **scope**:

| SAM parameter | Accepted claim names |
| --- | --- |
| `PortalRequiredAnalystRole` | `roles`, `role`, `app_role`, `application_role`, Keycloak `realm_access.roles`, nested `resource_access.*.roles` |
| `PortalRequiredAnalystScope` | `scope`, `scp`, `scopes` (space- or comma-separated string, or array) |

When `PortalJwtTenantId` is set, the Entra `tid` claim must match.

A valid access token **without** the configured role/scope returns **403**. No
token or an invalid token returns **401**.

Static SPA assets (`/`, `/cases`, etc.) are served **without** JWT; only `/api/*`
case and chat routes require authentication.

## Reference: Amazon Cognito user pool

Use when you do not already have a corporate IdP. Adapt names to your org.

1. **Create user pool** in `us-east-1` with MFA per org policy; create app client (PKCE for public SPA)
2. **Note issuer and audience** — issuer: `https://cognito-idp.us-east-1.amazonaws.com/<user-pool-id>`; audience: app client id or resource-server identifier
3. **Define analyst grant** — scope (e.g. `portal:analyst` -> `PortalRequiredAnalystScope`) or role via group/`custom:roles` -> `PortalRequiredAnalystRole`
4. **Create test user**, obtain access token, verify `iss`, `aud`, `sub`, role/scope
5. **Set SAM parameters** at deploy; build SPA with `VITE_PORTAL_AUTH_MODE=manual` or `entra` if the SPA performs hosted UI sign-in

Cognito is one option; Okta, Azure AD / Entra, Keycloak, or corporate OIDC work
the same way when they expose RS256/ES256 JWKS and the claims above.

## Map claims to SAM parameters (examples)

| IdP style | `PortalJwtIssuer` | `PortalJwtAudience` | Grant |
| --- | --- | --- | --- |
| Cognito user pool | `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_abc123` | App client id | `PortalRequiredAnalystScope=portal/read` |
| Keycloak | `https://auth.customer.example/realms/soc` | `notable-portal` | `PortalRequiredAnalystRole=analyst` |
| Okta | `https://customer.okta.com/oauth2/default` | `api://notable-portal` | `PortalRequiredAnalystScope=portal:analyst` |
| Microsoft Entra | `https://login.microsoftonline.com/<tenant-id>/v2.0` | API app client id | `PortalRequiredAnalystScope=api://<api-app-id>/portal.analyst` or `PortalRequiredAnalystRole=Analyst` |

Use comma-separated values for multiple allowed roles or scopes.

## Browser and CORS

`PortalCorsAllowedOrigins` must list the **exact origin** the browser uses
(scheme + host + port, no path). The portal SPA calls the regional API Gateway URL;
your edge DNS may front that URL but CORS must match the origin the browser sends.

The product does not provision CloudFront, ALB, or WAF — customer network edge is
out of scope for v1.

## Validation

Expected API results (run after deploy with curl or browser):

1. **Without token** — `GET /api/cases` returns **401**
2. **Valid access token, wrong scope/role** — **403**
3. **Valid analyst access token** — **200** with case list JSON
4. **CORS** — browser preflight from configured origin succeeds
5. **Entra SPA** — interactive sign-in yields an access token with correct `aud`;
   ID token must not be used against `/api/*`
6. **E2E** — optional `PORTAL_E2E_JWT` smoke per [`../../testing/TESTING.md`](../../testing/TESTING.md)

Obtain short-lived test access tokens; do not commit tokens to git or bake them
into static assets.

## IAM mode (API-only)

Set `PortalAuthMode=iam` for SigV4-signed automation and operator scripts. API
Gateway uses `AWS_IAM`; analysts do not sign in through the browser with IAM
credentials. Browser-based analyst access requires `PortalAuthMode=jwt` and a
customer IdP or `manual` / `entra` SPA token acquisition. IAM/SigV4 Playwright
automation is outside the shipped frontend E2E suite.

## Next

- **Path B step 6:** [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- **Path C:** same when `analyst_portal` is in the profile set — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- SPA build and auth modes: [`../../../frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md)
- Day-two portal ops: [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md)
