# AWS Analyst Portal UI

Canonical guide for building, configuring, and uploading the commercial AWS
read-only analyst portal SPA (React + Vite + Tailwind). Stack architecture, auth,
and contracts: [`docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
Visual design: [`docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md).

## Prerequisites

- Node.js and npm (system install; not the repo `.venv` / `nodeenv` bootstrap).
- JWT from the configured IdP (`PortalJwtIssuer` / `PortalJwtAudience`) for manual
  calls against protected routes on a deployed stack.

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
Supply a JWT in the browser (see [Browser JWT auth](#browser-jwt-auth)).

### Local dev with the Vite proxy

When `VITE_PORTAL_API_BASE_URL` is unset, the dev server proxies `/api`,
`/health`, and `/ready` to `VITE_PORTAL_API_TARGET` (default `http://127.0.0.1:8765`)
with dev-only headers (`X-Forwarded-User`, `X-Notable-Portal-Proxy-Secret`).
For local backends with proxy auth only — **not** the production AWS JWT API.

## Environment overrides

| Variable | Purpose |
|----------|---------|
| `VITE_PORTAL_API_BASE_URL` | Baked at build time; cross-origin API in dev. Leave unset for same-origin regional API when `PortalUiBucketName` is set. |
| `VITE_PORTAL_API_TARGET` | Vite dev proxy target (default `http://127.0.0.1:8765`). |
| `VITE_PORTAL_DEV_USER` | Dev proxy user header. |
| `VITE_PORTAL_DEV_PROXY_SECRET` | Dev proxy secret header. |

`VITE_PORTAL_API_TARGET` and `VITE_PORTAL_DEV_*` are ignored in production static assets.

## Browser JWT auth

Client sends `Authorization: Bearer <token>` when a token is stored under
`notable.portal.jwt` in `sessionStorage` or `localStorage`:

```javascript
sessionStorage.setItem("notable.portal.jwt", "<jwt>");
```

Do not bake JWTs into `.env` files or static assets. Tokens must come from the
customer IdP or an approved front-door auth flow.

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
$env:PORTAL_E2E_JWT = "<short-lived-jwt>"
$env:PORTAL_E2E_CASE_ID = "<ready-case-id>"
$env:PORTAL_E2E_CHAT = "true"
npm --prefix frontend/analyst-portal run test:e2e
```

Commercial AWS: set `PORTAL_E2E_AUTH_MODE=jwt` and a short-lived `PORTAL_E2E_JWT`.
JWT mode disables Playwright traces so the bearer token is not persisted.
IAM/SigV4 browser automation is outside this suite.

For HTTP Basic-auth previews: `PORTAL_E2E_AUTH_MODE=basic` plus `PORTAL_E2E_USER`
and `PORTAL_E2E_PASSWORD`.

| Variable | Purpose |
|----------|---------|
| `PORTAL_E2E_BASE_URL` | Portal origin (`PortalBrowserApiBaseUrl` for commercial AWS) |
| `PORTAL_E2E_AUTH_MODE` | `jwt` (commercial API Gateway) or `basic` (local preview) |
| `PORTAL_E2E_JWT` | Required short-lived bearer token when auth mode is `jwt` |
| `PORTAL_E2E_CASE_ID` | Known archived case in the target environment |
| `PORTAL_E2E_CHAT` | Run selected/global chat checks (`true` / `false`) |
| `PORTAL_E2E_CHAT_TIMEOUT_MS` | Chat response wait (default `180000`) |
| `PORTAL_E2E_USER` / `PORTAL_E2E_PASSWORD` | Basic-auth preview credentials |

## Deploy path — next

- **Path B (step 12):** [`../../docs/testing/TESTING.md`](../../docs/testing/TESTING.md) — OpenSearch preflight and customer-default smoke
