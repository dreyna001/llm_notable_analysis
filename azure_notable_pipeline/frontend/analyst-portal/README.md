# Azure Analyst Portal UI

Canonical guide for building, configuring, and uploading the Azure Government
read-only analyst portal SPA (React + Vite + Tailwind). Stack architecture,
auth, and contracts:
[`docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
Visual design:
[`docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md`](../../docs/operations/analyst_portal/ANALYST_PORTAL_THEME.md).

**Azure Government production deploy:** Front Door Premium routes all browser
traffic to private `$web` and the portal Function over Private Link. Follow
[`docs/operations/ANALYST_PORTAL_DEPLOYMENT.md`](../../docs/operations/ANALYST_PORTAL_DEPLOYMENT.md)
for the deploy gate, origin approval, and authenticated `/ready` validation.
`scripts/setup-and-deploy.sh` and `.ps1` also build, test, and upload `dist/`
when portal UI hosting is enabled.

## Prerequisites

- Node.js and npm on the workstation or CI runner (system install; not the on-prem
  repo `.venv` / `nodeenv` bootstrap).
- Deployed portal stack for browser validation, or mocked API responses for unit
  tests.
- An OIDC public-client SPA registration with authorization-code + PKCE enabled,
  the Front Door origin registered as a redirect URI, and delegated access to
  the portal API scope.

## Quick start

From the **repository root**:

```powershell
npm --prefix frontend/analyst-portal install
npm --prefix frontend/analyst-portal test
```

Local UI dev server:

```powershell
npm --prefix frontend/analyst-portal run dev
```

Open http://127.0.0.1:5173/

### Local dev against a deployed Azure portal

Point the Vite app at the stack browser API origin and configure browser OIDC:

```powershell
$env:VITE_PORTAL_API_BASE_URL = "https://<portal-browser-api-origin>"
$env:VITE_PORTAL_OIDC_CLIENT_ID = "<spa-client-id>"
$env:VITE_PORTAL_OIDC_AUTHORITY = "https://login.microsoftonline.us/<tenant-id>"
$env:VITE_PORTAL_OIDC_API_SCOPE = "api://<portal-api-app-id>/Portal.Access"
npm --prefix frontend/analyst-portal run dev
```

Use the Bicep output `PortalBrowserApiBaseUrl` when UI hosting is enabled. For
diagnostics, the deployment also returns `PortalApiUrl` and `PortalChatUrl`.

When the SPA origin (`http://127.0.0.1:5173`) differs from the API hostname, add
that origin to the stack parameter `PortalCorsAllowedOrigins` (or
`PORTAL_CORS_ALLOWED_ORIGINS` in non-template env).

### Local dev with the Vite proxy (same-origin to localhost)

When `VITE_PORTAL_API_BASE_URL` is unset, the dev server proxies `/api`,
`/health`, and `/ready` to `VITE_PORTAL_API_TARGET` (default
`http://127.0.0.1:8765`) and injects dev-only proxy headers
(`X-Forwarded-User`, `X-Notable-Portal-Proxy-Secret`). That path is for local
backends that accept proxy auth (on-prem preview/nginx style), **not** for the
production Azure JWT API.

## Environment overrides

```text
VITE_PORTAL_API_BASE_URL=https://<portal-browser-api-origin>
VITE_PORTAL_API_TARGET=http://127.0.0.1:8765
VITE_PORTAL_DEV_USER=dev-preview@local
VITE_PORTAL_DEV_PROXY_SECRET=portal-secret
VITE_PORTAL_OIDC_CLIENT_ID=<spa-client-id>
VITE_PORTAL_OIDC_AUTHORITY=https://login.microsoftonline.us/<tenant-id>
VITE_PORTAL_OIDC_API_SCOPE=api://<portal-api-app-id>/Portal.Access
```

- `VITE_PORTAL_API_BASE_URL` — baked at build time; also used at dev time for
  cross-origin calls to a deployed API. Leave unset for Front Door same-origin
  deploys (recommended when `PortalUiBucketName` is set).
- `VITE_PORTAL_API_TARGET` / `VITE_PORTAL_DEV_*` — Vite dev proxy only; ignored
  in production static assets.

## Browser OIDC authentication

The SPA uses MSAL authorization-code + PKCE. A clean browser displays **Sign
in**, processes the redirect, silently refreshes API access tokens, and clears
MSAL, legacy token, and chat-session state on logout. The app registration must
allow the exact production Front Door origin as a SPA redirect URI. Do not bake
tokens or client secrets into `.env` files or static assets; this is a public
client and requires no secret.

In JWT mode, the final scope name in `VITE_PORTAL_OIDC_API_SCOPE` must equal
`PORTAL_ENTRA_REQUIRED_APP_ROLE` (for example, both use `Portal.Access`). The
Function enforces that value from the token's `scp` or `roles` claim.

## Build and production upload

```powershell
npm --prefix frontend/analyst-portal run build
```

Output: `dist/`.

**Front Door same-origin deployment (required):** leave
`VITE_PORTAL_API_BASE_URL` unset. Upload `dist/` to the dedicated account's
`$web` container using Entra auth (`az storage blob upload-batch --auth-mode
login`). Front Door routes `/api/*` directly to the portal Function and uses
`index.html` as the Storage static-site 404 document. Both origins use Private
Link, and direct public origin access remains disabled.

**Split UI and API hostnames:** set the API base at build time, ensure
`PortalCorsAllowedOrigins` includes the exact SPA browser origin, then build
and upload as above.

Production deploy gate, private-endpoint approval, and rollback:
[`docs/operations/ANALYST_PORTAL_DEPLOYMENT.md`](../../docs/operations/ANALYST_PORTAL_DEPLOYMENT.md).

Example keyless upload after build from a private-network-connected runner:

```powershell
az storage blob upload-batch --auth-mode login --account-name <PortalUiStorageAccountName> --destination '$web' --source frontend/analyst-portal/dist --overwrite true
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
npm --prefix frontend/analyst-portal run install:e2e-browsers
```

Set the portal origin and a known archived case before running:

```powershell
$env:PORTAL_E2E_BASE_URL = "https://<PortalUiDistributionDomainName-or-custom-host>"
$env:PORTAL_E2E_CASE_ID = "<ready-case-id>"
$env:PORTAL_E2E_CHAT = "true"
npm --prefix frontend/analyst-portal run test:e2e
```

For deployments with HTTP basic auth in front of the portal (on-prem nginx
pattern, not the Azure Front Door deployment), also set `PORTAL_E2E_USER` and
`PORTAL_E2E_PASSWORD`. The default Playwright config still sends basic-auth
credentials; clear or override them when the front door is JWT-only.

OIDC-protected Azure portals redirect an empty browser through the configured
identity provider. Interactive E2E runs must complete that sign-in; unattended
CI should use an organization-approved Playwright authentication setup with a
short-lived test identity. The portal does not support bearer-token injection
through persistent browser storage.

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORTAL_E2E_BASE_URL` | `https://127.0.0.1:8443` | Portal origin (use the Front Door hostname) |
| `PORTAL_E2E_USER` | `analyst` | HTTP basic-auth user when a basic-auth front door is present |
| `PORTAL_E2E_PASSWORD` | `analyst-lab-change-me` | HTTP basic-auth password when a basic-auth front door is present |
| `PORTAL_E2E_CASE_ID` | `portal-test-1780770539` | Sample archived case in the target environment |
| `PORTAL_E2E_CHAT` | `true` | Run selected/global chat checks |
| `PORTAL_E2E_CHAT_TIMEOUT_MS` | `180000` | Chat response wait |

## Deploy path — next

- **Path B (step 9):** [`../../docs/operations/testing/AZURE_GOVERNMENT_TESTING.md`](../../docs/operations/testing/AZURE_GOVERNMENT_TESTING.md) — staging gate and customer-default validation
