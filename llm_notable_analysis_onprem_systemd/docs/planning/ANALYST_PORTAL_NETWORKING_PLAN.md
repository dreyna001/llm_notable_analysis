# Analyst Portal Networking Plan

## Status

Planning document for how analysts reach the on-prem portal over the internal
network. It records the expected deployment shape for the first portal slice.

**Operator rollout steps:** use the consolidated runbook
[`operations/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).

## Goal

Analysts should open a normal internal HTTPS URL in their browser, such as:

```text
https://notable-portal.<internal-domain>
```

They should not SSH into the analyzer host or manually browse local files to use
the portal.

## Recommended V1 Network Shape

```text
Analyst browser
-> internal DNS name: notable-portal.<internal-domain>
-> nginx listening on TCP 443
-> FastAPI / Uvicorn on 127.0.0.1:8080
-> Postgres notable_cases schema
```

Use nginx as the first documented reverse proxy path. FastAPI/Uvicorn stays
bound to loopback and is not exposed directly to the network.

## Required Operator Inputs

Before deployment, operators need to provide or approve:

- Internal hostname, for example `notable-portal.soc.local`.
- Portal host IP address.
- Internal DNS record mapping the hostname to the portal host.
- TLS certificate and private key for the hostname.
- Auth method for v1, defaulting to nginx basic auth unless customer SSO is
  already available.
- Analyst source networks allowed to reach TCP `443`.
- Whether nginx runs on the analyzer host or on a separate internal web host.

## DNS

Production should use internal DNS, usually AD DNS or the customer’s internal
DNS platform:

```text
notable-portal.soc.local -> 10.10.20.15
```

Hosts-file entries are acceptable only for local/lab validation.

## TLS

Nginx terminates HTTPS. Certificate options:

- Internal corporate CA certificate for the portal hostname.
- Existing internal wildcard certificate.
- Self-signed certificate for lab-only testing.

Expected nginx paths can be customer-specific, but examples may use:

```text
/etc/ssl/notable-portal/fullchain.pem
/etc/ssl/notable-portal/privkey.pem
```

## Firewall And Routing

Minimum access:

```text
analyst subnets -> portal host TCP 443
portal service -> Postgres TCP 5432
nginx -> FastAPI loopback 127.0.0.1:8080
```

FastAPI should not listen directly on the analyst network.

## Nginx Responsibilities

Nginx owns:

- External/internal listener on `443`.
- TLS termination.
- First documented auth path, likely basic auth.
- Optional customer SSO handoff later.
- Request size limits.
- Reverse proxy to FastAPI loopback.
- Access logs.

Conceptual config:

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

## FastAPI Responsibilities

FastAPI owns:

- Portal API routes and health/readiness probes.
- Case list/detail API.
- Chat request validation and responses.
- Postgres reads from `notable_cases`.
- Optional bounded chat-history writes if enabled.

Default bind:

```text
PORTAL_BIND_HOST=127.0.0.1
PORTAL_PORT=8080
```

## Auth Decision For V1

Assume all authenticated analysts can see all retained notables.

First documented path:

- nginx basic auth for lab/simple internal deployments.
- Customer SSO/reverse-proxy auth can replace basic auth later without changing
  the FastAPI app shape.

## Local Development

Local dev can skip nginx and run FastAPI directly on loopback:

```text
http://127.0.0.1:8080
```

This is for development only. Production/staging portal access should go through
nginx and HTTPS.

## Out Of Scope For V1

- Public internet exposure.
- Per-case RBAC.
- Analyst self-service account management.
- Portal-triggered Splunk, ServiceNow, SOAR, or remediation actions.
- Direct Uvicorn exposure to the analyst network.

