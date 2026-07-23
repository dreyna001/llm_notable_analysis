# AWS Analyst Portal UI

Vendored React + Vite + Tailwind + shadcn-style SPA for the AWS read-only analyst
portal API (JWT browser auth, CloudFront/S3 static hosting).

Deploy and operator runbooks:
[`docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).

Visual design: "Federal SOC Dark" — see [docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md](../../docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md) (palette, fonts, radius, accessibility contrast notes, browser-openable mockup).

## Prerequisites

- Node.js and npm on the workstation or CI runner (system install; not the on-prem
  repo `.venv` / `nodeenv` bootstrap).
- Deployed portal stack for browser validation, or mocked API responses for unit
  tests.
- A JWT from the configured identity provider (`PortalJwtIssuer` /
  `PortalJwtAudience`) for manual browser calls against protected routes.

## Quick start

From the **repository root**:

```powershell
npm --prefix s3_notable_pipeline/frontend/analyst-portal install
npm --prefix s3_notable_pipeline/frontend/analyst-portal test
```

Local UI dev server:

```powershell
npm --prefix s3_notable_pipeline/frontend/analyst-portal run dev
```

Open http://127.0.0.1:5173/

### Local dev against a deployed AWS portal

Point the Vite app at the stack browser API origin and supply a JWT in the
browser (see [Browser JWT auth](#browser-jwt-auth)):

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<portal-browser-api-origin>"
npm --prefix s3_notable_pipeline/frontend/analyst-portal run dev
```

Use the stack output `PortalBrowserApiBaseUrl` when UI hosting is enabled
(CloudFront with `/api/*` behaviors). For API-only deploys, use `PortalApiUrl` or
`PortalChatFunctionUrl` as documented in operations.

When the SPA origin (`http://127.0.0.1:5173`) differs from the API hostname, add
that origin to the stack parameter `PortalCorsAllowedOrigins` (or
`PORTAL_CORS_ALLOWED_ORIGINS` in non-template env).

### Local dev with the Vite proxy (same-origin to localhost)

When `VITE_PORTAL_API_BASE_URL` is unset, the dev server proxies `/api`,
`/health`, and `/ready` to `VITE_PORTAL_API_TARGET` (default
`http://127.0.0.1:8765`) and injects dev-only proxy headers
(`X-Forwarded-User`, `X-Notable-Portal-Proxy-Secret`). That path is for local
backends that accept proxy auth (on-prem preview/nginx style), **not** for the
production AWS JWT API.

## Environment overrides

```text
VITE_PORTAL_API_BASE_URL=https://<portal-browser-api-origin>
VITE_PORTAL_API_TARGET=http://127.0.0.1:8765
VITE_PORTAL_DEV_USER=dev-preview@local
VITE_PORTAL_DEV_PROXY_SECRET=portal-secret
```

- `VITE_PORTAL_API_BASE_URL` — baked at build time; also used at dev time for
  cross-origin calls to a deployed API. Leave unset for CloudFront same-origin
  deploys (recommended when `PortalUiBucketName` is set).
- `VITE_PORTAL_API_TARGET` / `VITE_PORTAL_DEV_*` — Vite dev proxy only; ignored
  in production static assets.

## Browser JWT auth

The client sends `Authorization: Bearer <token>` when a token is present under
`notable.portal.jwt` in `sessionStorage` or `localStorage`.

For manual validation in a browser console:

```javascript
sessionStorage.setItem("notable.portal.jwt", "<jwt>");
```

Do not bake JWTs into `.env` files or static assets. Tokens should come from the
customer identity provider or an approved front-door auth flow.

## Build

Build static assets for S3/CloudFront:

```powershell
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
```

Output: `dist/`.

**CloudFront UI with in-stack API behaviors (recommended):** leave
`VITE_PORTAL_API_BASE_URL` unset. Upload `dist/` to the stack
`PortalUiBucketName` bucket. CloudFront serves the SPA from S3, routes `/api/*`
to API Gateway, `/api/chat` to the Function URL when enabled, and maps 403/404 to
`/index.html` for client-side routing. S3 public access stays blocked; access is
via CloudFront origin access control.

**Split UI and API hostnames:** set the API base at build time:

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<PortalBrowserApiBaseUrl>"
npm --prefix s3_notable_pipeline/frontend/analyst-portal run build
```

Ensure `PortalCorsAllowedOrigins` includes the exact SPA browser origin.

Example upload after build (replace bucket name from stack output):

```powershell
aws s3 sync s3_notable_pipeline/frontend/analyst-portal/dist/ s3://<PortalUiBucketName>/ --delete
```

## Routes

| Path | Purpose |
|------|---------|
| `/` | Home + API health |
| `/cases` | Paginated case list |
| `/cases/:caseId` | Case detail (JSON inspection) |

## Playwright E2E (deployed portal)

Holistic browser checks against a deployed portal origin (list filters, case-detail
tabs, cross-links, error paths, optional chat). Optional dev/staging/prod checks;
not part of the default unit test suite.

Install Chromium once per machine:

```powershell
npm --prefix s3_notable_pipeline/frontend/analyst-portal run install:e2e-browsers
```

Set the portal origin and a known archived case before running:

```powershell
$env:PORTAL_E2E_BASE_URL = "https://<PortalUiDistributionDomainName-or-custom-host>"
$env:PORTAL_E2E_CASE_ID = "<ready-case-id>"
$env:PORTAL_E2E_CHAT = "true"
npm --prefix s3_notable_pipeline/frontend/analyst-portal run test:e2e
```

For deployments with HTTP basic auth in front of the portal (on-prem nginx
pattern, not the default AWS stack), also set `PORTAL_E2E_USER` and
`PORTAL_E2E_PASSWORD`. The default Playwright config still sends basic-auth
credentials; clear or override them when the front door is JWT-only.

JWT-protected AWS portals require a valid browser token before protected routes
load. The E2E harness does not inject JWTs automatically; set
`notable.portal.jwt` through your IdP flow or an approved test hook before
running chat and case-detail steps.

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORTAL_E2E_BASE_URL` | `https://127.0.0.1:8443` | Portal origin (use CloudFront or custom DNS for AWS) |
| `PORTAL_E2E_USER` | `analyst` | HTTP basic-auth user when a basic-auth front door is present |
| `PORTAL_E2E_PASSWORD` | `analyst-lab-change-me` | HTTP basic-auth password when a basic-auth front door is present |
| `PORTAL_E2E_CASE_ID` | `portal-test-1780770539` | Sample archived case in the target environment |
| `PORTAL_E2E_CHAT` | `true` | Run selected/global chat checks |
| `PORTAL_E2E_CHAT_TIMEOUT_MS` | `180000` | Chat response wait |
