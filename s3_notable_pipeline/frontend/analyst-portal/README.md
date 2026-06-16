# AWS Analyst Portal UI

Vendored React + Vite + Tailwind SPA for the AWS read-only analyst portal API.

## Prerequisites

- Node.js and npm available on the workstation or CI runner.
- Deployed portal API for browser validation, or mocked API responses for unit tests.
- A JWT from the configured identity provider for manual browser calls.

## Quick Start

From the repository root:

```powershell
npm --prefix s3_notable_pipeline/frontend/analyst-portal install
npm --prefix s3_notable_pipeline/frontend/analyst-portal test
```

Local dev uses same-origin requests when `VITE_PORTAL_API_BASE_URL` is unset.
For a deployed AWS API origin:

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<portal-api-origin>"
npm --prefix s3_notable_pipeline/frontend/analyst-portal run dev
```

The API must allow the browser origin through `PortalCorsAllowedOrigins`.

## Browser JWT Auth

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

Output: `dist/`. Upload this directory to the approved static hosting bucket and
configure SPA fallback to `/index.html`.

## Routes

| Path | Purpose |
|------|---------|
| `/` | Home + API health |
| `/cases` | Paginated case list |
| `/cases/:caseId` | Case detail |

## Playwright E2E

The E2E tests can run against a deployed AWS portal origin. These are optional
dev/staging/prod checks and are not part of the default unit test suite.

Set the base URL and a known archived case before running:

```powershell
$env:PORTAL_E2E_BASE_URL = "https://<portal-origin>"
$env:PORTAL_E2E_CASE_ID = "<ready-case-id>"
$env:PORTAL_E2E_CHAT = "true"
npm --prefix s3_notable_pipeline/frontend/analyst-portal run test:e2e
```
