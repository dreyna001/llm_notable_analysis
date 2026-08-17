# AWS Analyst Portal UI

Canonical guide for building, configuring, and uploading the commercial AWS
read-only analyst portal SPA (React + Vite + Tailwind). Stack architecture, auth,
and contracts: [`docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
Identity and Entra setup: [`docs/operations/deployment/PORTAL_JWT_IDENTITY.md`](../../docs/operations/deployment/PORTAL_JWT_IDENTITY.md).
Visual design: [`docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md).

## Prerequisites

- Node.js and npm (system install; not the repo `.venv` / `nodeenv` bootstrap).
- Deployed stack with `PortalAuthMode=jwt` for analyst browser use.
- Access token from the configured IdP for `manual` mode, or Entra app
  registrations for `entra` mode — see PORTAL_JWT_IDENTITY.md.

## Quick start

From the commercial project root (`s3_notable_pipeline_commercial/`):

```powershell
npm --prefix frontend/analyst-portal install
npm --prefix frontend/analyst-portal test
npm --prefix frontend/analyst-portal run dev
```

Open http://127.0.0.1:5173/

### Local dev against a deployed AWS portal

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<PortalBrowserApiBaseUrl>"
npm --prefix frontend/analyst-portal run dev
```

Use stack output `PortalBrowserApiBaseUrl` when UI hosting is enabled; `PortalApiUrl`
for API-only deployments. When the SPA origin differs from the API hostname, add
the dev origin to `PortalCorsAllowedOrigins` / `PORTAL_CORS_ALLOWED_ORIGINS`.
Supply an access token in `manual` mode (see [Browser auth modes](#browser-auth-modes)).

### Local dev with the Vite proxy

When `VITE_PORTAL_API_BASE_URL` is unset, the dev server proxies `/api`,
`/health`, and `/ready` to `VITE_PORTAL_API_TARGET` (default `http://127.0.0.1:8765`)
with dev-only headers (`X-Forwarded-User`, `X-Notable-Portal-Proxy-Secret`).
For local backends with proxy auth only — **not** the production AWS JWT API.

## Environment overrides

Copy `.env.example` to `.env.local` for a customer build and replace only the
documented placeholders. Do not place tokens or client secrets in Vite files.

| Variable | Purpose |
|----------|---------|
| `VITE_PORTAL_API_BASE_URL` | Baked at build time; cross-origin API in dev. Leave unset for same-origin regional API when `PortalUiBucketName` is set. |
| `VITE_PORTAL_API_TARGET` | Vite dev proxy target (default `http://127.0.0.1:8765`). |
| `VITE_PORTAL_DEV_USER` | Dev proxy user header. |
| `VITE_PORTAL_DEV_PROXY_SECRET` | Dev proxy secret header. |

`VITE_PORTAL_API_TARGET` and `VITE_PORTAL_DEV_*` are ignored in production static assets.

## Browser auth modes

`VITE_PORTAL_AUTH_MODE` is baked at build. It applies only when the deployed API
uses `PortalAuthMode=jwt`. Backend `PortalAuthMode=iam` is API-only (SigV4) and
is not a browser analyst path.

| Mode | Behavior |
|------|----------|
| `manual` (default) | Backward compatible. Operator or analyst supplies a short-lived API access token; SPA sends `Authorization: Bearer` from storage key `notable.portal.jwt`. |
| `entra` | Production Entra sign-in via MSAL browser PKCE (public SPA client, no client secret). Acquires a delegated API **access token** for `/api/*`. |
| `none` | No browser token acquisition or authorization header. Intended for unauthenticated local/proxy scenarios, not a protected production portal. |

### Manual token storage

```javascript
sessionStorage.setItem("notable.portal.jwt", "<access-token>");
```

Do not bake tokens into `.env` files or static assets.

### Entra production build

Set backend SAM parameters per PORTAL_JWT_IDENTITY.md (`PortalJwtIssuer`,
`PortalJwtAudience`, analyst grant, CORS, optional `PortalJwtTenantId`).
Register customer Entra API and SPA apps; use access tokens, not ID tokens.

```powershell
$env:VITE_PORTAL_AUTH_MODE = "entra"
$env:VITE_PORTAL_ENTRA_TENANT_ID = "<entra-directory-tenant-id>"
$env:VITE_PORTAL_ENTRA_CLIENT_ID = "<spa-client-id>"
$env:VITE_PORTAL_ENTRA_API_SCOPE = "api://<api-app-client-id>/portal.analyst"
$env:VITE_PORTAL_ENTRA_REDIRECT_URI = "https://<portal-origin>/"
$env:VITE_PORTAL_ENTRA_POST_LOGOUT_URI = "https://<portal-origin>/"
npm --prefix frontend/analyst-portal run build
```

Redirect and logout URIs must match Entra app registration exactly. Also register
`https://<portal-origin>/auth/silent.html` as a SPA redirect URI for silent token
renewal. The portal origin must appear in `PortalCorsAllowedOrigins`. Align
`PortalJwtAudience` with the API app client id or application id URI on issued
access tokens.

## Build and upload

```powershell
npm --prefix frontend/analyst-portal run build
```

Output: `dist/`.

**Regional same-origin UI (recommended):** leave `VITE_PORTAL_API_BASE_URL` unset.
Upload `dist/` to `PortalUiBucketName`. API Gateway routes all traffic to the
portal Lambda (static reads from private S3 plus `/api/*`, `/health`, `/ready`).

**Split UI and API hostnames:**

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<PortalBrowserApiBaseUrl>"
npm --prefix frontend/analyst-portal run build
```

Ensure `PortalCorsAllowedOrigins` includes the exact SPA browser origin.

```powershell
aws s3 sync frontend/analyst-portal/dist/ s3://<PortalUiBucketName>/ --region us-east-1
```

## Routes

| Path | Purpose |
|------|---------|
| `/` | Home + API health |
| `/cases` | Paginated case list |
| `/cases/:caseId` | Case detail (JSON inspection) |

## Playwright E2E (deployed portal)

Holistic browser checks (list filters, case-detail tabs, cross-links, error paths,
optional chat). Not part of the default unit test suite.

```powershell
npm --prefix frontend/analyst-portal run install:e2e-browsers

$env:PORTAL_E2E_BASE_URL = "https://<PortalBrowserApiBaseUrl>"
$env:PORTAL_E2E_AUTH_MODE = "jwt"
$env:PORTAL_E2E_JWT = "<short-lived-access-token>"
$env:PORTAL_E2E_CASE_ID = "<ready-case-id>"
$env:PORTAL_E2E_CHAT = "true"
npm --prefix frontend/analyst-portal run test:e2e
```

Commercial AWS: set `PORTAL_E2E_AUTH_MODE=jwt` and a short-lived access token in
`PORTAL_E2E_JWT`. JWT mode disables Playwright traces so the bearer token is not
persisted. IAM/SigV4 browser automation is outside this suite.

For HTTP Basic-auth previews: `PORTAL_E2E_AUTH_MODE=basic` plus `PORTAL_E2E_USER`
and `PORTAL_E2E_PASSWORD`.

| Variable | Purpose |
|----------|---------|
| `PORTAL_E2E_BASE_URL` | Portal origin (`PortalBrowserApiBaseUrl` for commercial AWS) |
| `PORTAL_E2E_AUTH_MODE` | `jwt` (commercial API Gateway) or `basic` (local preview) |
| `PORTAL_E2E_JWT` | Required short-lived access token when auth mode is `jwt` |
| `PORTAL_E2E_CASE_ID` | Known archived case in the target environment |
| `PORTAL_E2E_CHAT` | Run selected/global chat checks (`true` / `false`) |
| `PORTAL_E2E_CHAT_TIMEOUT_MS` | Chat response wait (default `180000`) |
| `PORTAL_E2E_USER` / `PORTAL_E2E_PASSWORD` | Basic-auth preview credentials |

## Deploy path — next

- **Path B (step 12):** [`../../docs/testing/TESTING.md`](../../docs/testing/TESTING.md) — OpenSearch preflight and customer-default smoke
