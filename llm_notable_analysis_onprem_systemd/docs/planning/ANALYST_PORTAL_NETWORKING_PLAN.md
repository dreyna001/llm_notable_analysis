# Analyst Portal Networking Plan

## Status

Design rationale for how analysts reach the on-prem portal over the internal
network. **Shipped.**

**Rollout steps are superseded** by the operator runbook
[`operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).
Use that doc for install, TLS, htpasswd, DNS, firewall, and browser validation.

This plan records why v1 is shaped this way and points at shipped artifacts.
It does not duplicate step-by-step cutover.

## Goal

Analysts open a normal internal HTTPS URL in a browser:

```text
https://notable-portal.<internal-domain>
```

They do not SSH into the analyzer host or browse local files to use the portal.

## Shipped V1 Network Shape

```text
Analyst browser (allowed subnets)
  -> internal DNS: notable-portal.<internal-domain>  (TCP 443)
  -> nginx on portal host (TLS, basic auth, React SPA, API proxy)
  -> FastAPI on 127.0.0.1:8080 (loopback only; not on analyst network)
  -> Postgres notable_cases schema on 127.0.0.1:5432
```

nginx terminates HTTPS, serves the built React SPA from disk, and proxies
`/api/*`, `/health`, and `/ready` to loopback FastAPI. Case routes fail closed
without nginx auth and the shared proxy-secret header.

## Design Rationale (Still Current)

| Decision | Rationale |
|----------|-----------|
| nginx as the documented front door | TLS, auth, static SPA, rate limits, and access logs stay out of FastAPI |
| FastAPI on loopback only | Analyst subnets never reach Uvicorn directly; `PORTAL_ALLOW_NON_LOOPBACK_BIND=false` by default |
| nginx basic auth for v1 | Simple internal rollout; customer SSO can replace auth at nginx later |
| Shared `PORTAL_PROXY_SECRET` | nginx sets `X-Notable-Portal-Proxy-Secret` on API routes so direct loopback callers cannot impersonate authenticated users |
| Trusted user from nginx only | `PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User`; set by nginx after basic auth |
| Flat case visibility in v1 | All authenticated analysts see all retained cases; no per-case RBAC yet |
| Same host as analyzer (default) | `install.sh` assumes co-located nginx; a separate internal web host is OK if the proxy path and secrets are preserved |

## Shipped Artifacts

| Artifact | Role |
|----------|------|
| [`scripts/install.sh`](../../scripts/install.sh) with `INSTALL_ANALYST_PORTAL=true` | Opt-in portal bring-up: `analyst_portal` profile, `portal.env`, Postgres schema, SPA build, nginx site + proxy-secret include, `notable-portal.service` |
| [`deploy/nginx/notable-portal.conf`](../../deploy/nginx/notable-portal.conf) | Authoritative nginx example (SPA root, API locations, chat rate limit, TLS paths) |
| [`config.portal.env.example`](../../config.portal.env.example) | Portal env contract (`PORTAL_BIND_HOST`, `PORTAL_PROXY_SECRET`, DSN, LLM URL) |
| [`deploy/systemd/notable-portal.service`](../../deploy/systemd/notable-portal.service) | Portal systemd unit |

**Installer automates:** portal env and generated proxy secret, nginx config copy
(when nginx is present), frontend build to
`/opt/notable-analyzer/frontend/analyst-portal/dist`, Postgres case-archive
setup, and best-effort service start.

**Operator still required after install:** TLS certificate and key, htpasswd
users, `server_name` and cert paths in nginx, internal DNS, firewall, and
analyst-workstation validation. See the network deployment runbook.

Skip flags when assets are pre-staged: `INSTALL_PORTAL_SKIP_OS_PACKAGES=true`,
`INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true`, or
`INSTALL_PORTAL_ALLOW_PARTIAL=true` (files only, no DB).

## Required Operator Inputs

Before cutover, operators provide or approve:

- Internal hostname (nginx `server_name`, TLS SAN).
- Portal host IP (DNS A record target).
- TLS certificate and private key.
- Analyst subnets allowed to reach TCP `443`.
- Auth method (nginx basic auth is v1 default).
- nginx placement (same host as analyzer, or separate internal web host).

## DNS And Firewall

Internal DNS (AD or customer DNS platform):

```text
notable-portal.soc.local -> 10.10.20.15
```

Hosts-file entries are lab-only, not production.

Minimum connectivity:

```text
analyst subnets  -> portal host TCP 443
portal host      -> Postgres TCP 5432 (loopback or local)
nginx            -> FastAPI 127.0.0.1:8080 (loopback only)
```

Do not expose TCP `8080` to analyst subnets.

## TLS And Auth (Shipped Paths)

nginx terminates HTTPS. Shipped example paths (customer paths may differ):

```text
/etc/nginx/tls/notable-portal.crt
/etc/nginx/tls/notable-portal.key
/etc/nginx/htpasswd/notable-portal
```

Certificate sources: internal CA, internal wildcard, or self-signed (lab only).

Basic-auth users are **not** created by `install.sh`; operators create htpasswd
entries through their credential process. nginx forwards the authenticated
username as `X-Forwarded-User`.

API routes include `/etc/nginx/notable-portal-proxy-secret.conf`, which must
match `PORTAL_PROXY_SECRET` in `/etc/notable-analyzer/portal.env`.

## FastAPI Boundaries

FastAPI owns portal API routes, health/readiness, chat validation, and Postgres
reads from `notable_cases`. Default bind:

```text
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
```

Production UI is the React SPA served by nginx, not FastAPI templates.

## Local Development

Local dev may skip nginx and hit loopback directly (`http://127.0.0.1:8080`).
That path is development-only. For workstation preview without production Postgres
or nginx, see
[`operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md`](../operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md).

## Superseded By Shipped Rollout

The following early-plan details are **superseded**. Do not copy them for new
deployments; use the shipped nginx config and network deployment runbook instead.

| Superseded (planning draft) | Shipped replacement |
|-----------------------------|---------------------|
| Single `location /` proxy to FastAPI | nginx serves SPA at `root`; separate `/api/`, `/api/chat`, `/health`, `/ready` proxy blocks — see [`deploy/nginx/notable-portal.conf`](../../deploy/nginx/notable-portal.conf) |
| TLS under `/etc/ssl/notable-portal/` | `/etc/nginx/tls/notable-portal.{crt,key}` in shipped nginx example |
| htpasswd at `/etc/nginx/notable-portal.htpasswd` | `/etc/nginx/htpasswd/notable-portal` |
| Conceptual nginx snippet below | Full shipped config (HTTP->HTTPS redirect, chat rate limit, `$http_host` on API routes, proxy-secret include) |

<details>
<summary>Superseded conceptual nginx snippet (historical only)</summary>

```nginx
server {
    listen 443 ssl;
    server_name notable-portal.soc.local;

    ssl_certificate /etc/ssl/notable-portal/fullchain.pem;
    ssl_certificate_key /etc/ssl/notable-portal/privkey.pem;

    auth_basic "Notable Portal";
    auth_basic_user_file /etc/nginx/notable-portal.htpasswd;

    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-User $remote_user;
    }
}
```

</details>

## Out Of Scope For V1

- Public internet exposure.
- Per-case RBAC or analyst self-service account management.
- Portal-triggered Splunk, ServiceNow, SOAR, or remediation actions.
- Direct Uvicorn exposure on the analyst network.
- SSO nginx example in-repo (basic auth documented first; customer SSO at nginx
  is a later operator swap).

## Related Docs

- [`operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) — rollout runbook (authoritative for cutover)
- [`operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — day-two portal ops
- [`operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md`](../operations/analyst_portal/ANALYST_PORTAL_CHAT_SECURITY.md) — LLM boundaries
- [`operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md) — base host install
- [`technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md) — implementation contract
