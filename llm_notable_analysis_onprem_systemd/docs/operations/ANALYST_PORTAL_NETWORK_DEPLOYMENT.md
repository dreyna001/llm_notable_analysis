# Analyst Portal Network Deployment

Step-by-step guide to serve the on-prem analyst portal on the internal network
so analysts open a normal HTTPS URL in a browser. They should not SSH into the
analyzer host to use the portal.

For day-two portal operations (chunk rebuild, backfill, chat guardrails), see
[`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md). For workstation
preview without production Postgres or nginx, see
[`ANALYST_PORTAL_PREVIEW.md`](ANALYST_PORTAL_PREVIEW.md).

## What This Controls

- How analysts reach the portal over the internal network.
- nginx TLS, basic auth, static SPA, and API proxy to loopback FastAPI.
- Internal DNS, firewall, and validation from an analyst workstation.

This guide does not change portal application code. It wires the shipped
services and config into a customer network.

## Target Shape

```text
Analyst browser (any workstation on allowed subnets)
  -> https://notable-portal.<internal-domain>  (TCP 443)
  -> nginx on portal host (TLS, basic auth, React SPA, API proxy)
  -> FastAPI on 127.0.0.1:8080 (not exposed to analyst network)
  -> Postgres notable_cases schema on 127.0.0.1:5432
```

FastAPI must stay on loopback (`PORTAL_BIND_HOST=127.0.0.1`). Analysts never
browse `http://127.0.0.1:8080` for normal use; that port is API-only and case
routes fail closed without nginx auth and the proxy secret header.

## Before You Start

Collect or approve these inputs before cutover:

| Input | Example | Notes |
|-------|---------|-------|
| Internal hostname | `notable-portal.soc.local` | Used in nginx `server_name` and TLS SAN |
| Portal host IP | `10.10.20.15` | DNS A record target |
| TLS certificate + key | Corp CA or internal wildcard | nginx terminates HTTPS |
| Analyst subnets | `10.10.0.0/16` | Allowed to reach host TCP `443` |
| Auth method | nginx basic auth (v1 default) | Customer SSO can replace later |
| nginx placement | Same host as analyzer (default) | Separate internal web host is OK if proxy path is preserved |

Out of scope for v1:

- Public internet exposure.
- Per-case RBAC or analyst self-service account management.
- Exposing Uvicorn directly on the analyst network.

## Step 1 — Install the base analyzer stack

On the portal host, complete a normal on-prem install if not already done. See
[`INSTALL.md`](INSTALL.md).

Minimum runtime for portal chat:

- LiteLLM reachable at `LLM_API_URL` (default `http://127.0.0.1:4000`).
- Mixedbread embedder staged under `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` when
  case Q&A retrieval is required. See [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md).

## Step 2 — Install portal application assets

Full portal wiring is opt-in:

```bash
cd /opt/llm-notable-analysis/llm_notable_analysis_onprem_systemd
sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

That flag:

- Adds `analyst_portal` to `CAPABILITY_PROFILES` in `/etc/notable-analyzer/config.env` when missing.
- Writes `/etc/notable-analyzer/portal.env` with a generated `PORTAL_PROXY_SECRET`.
- Synchronizes the proxy secret into `config.env` for analyzer profile validation.
- Generates Postgres passwords in env files when localhost DSNs omit passwords.
- Runs `scripts/setup_postgres_case_archive.sh` (roles, database, `notable_cases` schema).
- Builds the React SPA to `/opt/notable-analyzer/frontend/analyst-portal/dist`.
- Copies `deploy/nginx/notable-portal.conf` to `/etc/nginx/conf.d/` when nginx is installed.
- Writes `/etc/nginx/notable-portal-proxy-secret.conf` for the shared secret header.
- Best-effort starts `notable-portal.service`.

Skip automated OS packages or frontend build only when those assets are already staged:

```bash
sudo INSTALL_PORTAL_SKIP_OS_PACKAGES=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
sudo INSTALL_PORTAL_SKIP_FRONTEND_BUILD=true INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

Use `INSTALL_PORTAL_ALLOW_PARTIAL=true` only when intentionally staging files before database access exists.

Manual Postgres path after editing env files:

```bash
sudo bash scripts/setup_postgres_case_archive.sh \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
```

## Step 3 — Confirm portal env and systemd

Review `/etc/notable-analyzer/portal.env`. Recommended values:

```bash
CAPABILITY_PROFILES=core,analyst_portal
CASE_POSTGRES_DSN=postgresql://notable_portal@127.0.0.1:5432/notable_rag
CASE_POSTGRES_SCHEMA=notable_cases
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
PORTAL_TRUSTED_USER_HEADER=X-Forwarded-User
PORTAL_ALLOW_NON_LOOPBACK_BIND=false
PORTAL_PROXY_SECRET=<must-match-nginx-include>
PORTAL_PROXY_SECRET_HEADER=X-Notable-Portal-Proxy-Secret
LLM_API_URL=http://127.0.0.1:4000/v1/chat/completions
```

Enable and start the portal service if the installer did not:

```bash
sudo cp deploy/systemd/notable-portal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now notable-portal.service
sudo systemctl status notable-portal.service
```

Loopback API checks (operators on the host):

```bash
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
```

`/ready` returns `503` until case archive tables exist and the portal role can read them.

## Step 4 — Stage TLS certificates

Place the internal certificate and private key on the portal host. Example paths
(match your nginx config):

```text
/etc/nginx/tls/notable-portal.crt
/etc/nginx/tls/notable-portal.key
```

Certificate options:

- Internal corporate CA certificate for the portal hostname.
- Existing internal wildcard certificate.
- Self-signed certificate for lab-only testing (distribute trust to analyst browsers or accept warnings).

```bash
sudo mkdir -p /etc/nginx/tls /etc/nginx/htpasswd
sudo chmod 700 /etc/nginx/tls
sudo chown root:root /etc/nginx/tls/notable-portal.crt /etc/nginx/tls/notable-portal.key
sudo chmod 600 /etc/nginx/tls/notable-portal.key
```

## Step 5 — Configure nginx for your hostname

Edit the installed site config (installer default:

`/etc/nginx/conf.d/notable-portal.conf`). Example source:

`deploy/nginx/notable-portal.conf`.

Set customer-specific values:

1. `server_name` — your internal hostname (both `443` and `80` server blocks).
2. `ssl_certificate` and `ssl_certificate_key` — paths from Step 4.
3. `root` — must point at the built SPA:

   ```text
   /opt/notable-analyzer/frontend/analyst-portal/dist
   ```

4. Confirm `proxy_pass` targets `http://127.0.0.1:8080` for `/api/`, `/health`, and `/ready`.
5. Confirm API locations include:

   ```nginx
   include /etc/nginx/notable-portal-proxy-secret.conf;
   ```

   That file must contain a header matching `PORTAL_PROXY_SECRET` in
   `portal.env` (the installer creates it when nginx is present).

If you copy from the repo instead of using the installer copy:

```bash
sudo cp deploy/nginx/notable-portal.conf /etc/nginx/conf.d/notable-portal.conf
sudo vi /etc/nginx/conf.d/notable-portal.conf
sudo nginx -t
```

## Step 6 — Create analyst login credentials

Production basic-auth users are **not** created by the application installer.
Create nginx htpasswd entries through your approved credential process:

```bash
sudo htpasswd -c /etc/nginx/htpasswd/notable-portal <analyst-user>
# Add more users without -c:
sudo htpasswd /etc/nginx/htpasswd/notable-portal <second-analyst>
sudo nginx -t
sudo systemctl reload nginx
```

Lab-only shortcut (rotate before sharing the host):

```bash
sudo htpasswd -bc /etc/nginx/htpasswd/notable-portal analyst analyst-lab-change-me
```

v1 assumes all authenticated analysts can see all retained cases. nginx forwards
the basic-auth username as `X-Forwarded-User` after TLS and auth succeed.

## Step 7 — Create internal DNS

Create an internal DNS A record (AD DNS or your internal DNS platform):

```text
notable-portal.soc.local -> 10.10.20.15
```

Replace with your hostname and portal host IP. Hosts-file entries are acceptable
only for single-machine lab validation, not production rollout.

## Step 8 — Open firewall paths

Minimum connectivity:

```text
analyst subnets  -> portal host TCP 443
portal host      -> Postgres TCP 5432 (loopback or local Postgres)
nginx            -> FastAPI 127.0.0.1:8080 (loopback only)
```

Do **not** expose TCP `8080` to analyst subnets. Do **not** set
`PORTAL_ALLOW_NON_LOOPBACK_BIND=true` without an explicit network review.

## Step 9 — Reload nginx and verify services

```bash
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl is-active notable-portal.service nginx
```

On the portal host, optional HTTPS probe through nginx (uses basic auth):

```bash
curl -fsS -u '<analyst-user>:<password>' https://notable-portal.soc.local/health
curl -fsS -u '<analyst-user>:<password>' https://notable-portal.soc.local/ready
```

## Step 10 — Validate from an analyst workstation

From a machine on an allowed subnet **without SSH to the portal host**:

1. Open `https://notable-portal.soc.local/` in a browser.
2. Accept corporate TLS trust if using an internal CA (or install lab cert).
3. Log in with nginx basic auth.
4. Confirm the case list loads (`/cases`).
5. Open a case detail page.
6. Send a test chat message on a pinned case (if chat is enabled).
7. Optional: call `GET /api/capabilities` and confirm `chat_ready` when LLM and embeddings are up.

SSH tunnel (`local 8443 -> remote 443`) is a lab operator convenience only. It
is not the production access path for analysts.

## Step 11 — Populate case data (if empty)

New portal installs have no cases until the analyzer archives notables.

Optional legacy markdown import:

```bash
sudo /opt/notable-analyzer/venv/bin/python scripts/backfill_case_archive.py \
  --config-env /etc/notable-analyzer/config.env \
  --dry-run
```

After embedding model or dimension changes, rebuild chunks per
[`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md).

## Port Reference

| Listener | Address | Audience | Purpose |
|----------|---------|----------|---------|
| nginx HTTPS | `0.0.0.0:443` (typical) | Analysts on allowed subnets | SPA + authenticated API |
| nginx HTTP | `0.0.0.0:80` (typical) | Redirect to HTTPS | |
| FastAPI | `127.0.0.1:8080` | Loopback / nginx only | API, health, readiness |
| Postgres | `127.0.0.1:5432` (default) | Local services | Case archive |

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Browser cannot resolve hostname | DNS A record, client DNS suffix search |
| TLS error in browser | Certificate SAN, corp CA trust, cert/key paths in nginx |
| 401 at nginx | htpasswd user, `auth_basic_user_file` path |
| 403 on `/api/*` | `notable-portal-proxy-secret.conf` matches `PORTAL_PROXY_SECRET` |
| Empty case list | Analyzer archiving, retention, backfill; `/ready` on loopback |
| Chat unavailable | `GET /api/capabilities` `chat_ready`, LiteLLM, embedder cache |
| 502 from nginx | `notable-portal.service` running, `127.0.0.1:8080` reachable |

Logs:

```bash
sudo journalctl -u notable-portal.service -n 100 --no-pager
sudo tail -n 50 /var/log/nginx/notable-portal.error.log
```

## Related Docs

- [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md) — enable/disable, maintenance, API surface, chat readiness
- [`ANALYST_PORTAL_CHAT_SECURITY.md`](ANALYST_PORTAL_CHAT_SECURITY.md) — LLM boundaries
- [`INSTALL.md`](INSTALL.md) — full host install
- [`planning/ANALYST_PORTAL_NETWORKING_PLAN.md`](../planning/ANALYST_PORTAL_NETWORKING_PLAN.md) — design rationale (superseded for rollout steps by this doc)
- [`deploy/nginx/notable-portal.conf`](../../deploy/nginx/notable-portal.conf) — example nginx site
- [`deploy/systemd/notable-portal.service`](../../deploy/systemd/notable-portal.service) — portal systemd unit
