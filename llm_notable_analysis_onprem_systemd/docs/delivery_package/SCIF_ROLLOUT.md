# SCIF Rollout

## Purpose

Start with a localhost-only deployment that can be installed and demonstrated
without DNS, nginx, TLS certificates, production authentication, PostgreSQL, or
network exposure. Move to the production-shaped SCIF deployment only after the
local workflow is accepted.

This document distinguishes the three runtime shapes already present in the
repository:

1. Localhost portal preview for the current demonstration.
2. Real local vLLM, LiteLLM, and analyzer services.
3. Production-shaped portal and SCIF network rollout.

Repository paths in this document are intentionally written as paths rather
than hyperlinks.

## Recommended Current Scope

Use the localhost portal preview first.

In scope:

- Browser access on `http://127.0.0.1:5173`.
- Preview API on `http://127.0.0.1:8765`.
- Stored and synthetic cases.
- Stub chat with no credentials, or an explicitly configured LLM provider.
- Development-only proxy headers injected on loopback.
- Local health, readiness, case browsing, and chat workflow validation.

Explicitly deferred:

- DNS.
- nginx.
- TLS certificates.
- Basic Auth, OIDC, or production analyst account management.
- Firewall changes.
- PostgreSQL.
- systemd services.
- Production retention, backup, monitoring, and log forwarding.
- Splunk, ServiceNow, Elasticsearch, and writeback integrations.
- Any listener exposed beyond loopback.

## Option 1: Localhost Portal Preview

This is the existing path that most closely matches the current requirement.
It does not install the production on-prem service chain.

### Behavior

| Component | Localhost preview behavior |
| --- | --- |
| React UI | Vite on `127.0.0.1:5173` |
| Portal API | FastAPI on `127.0.0.1:8765` |
| Cases 1-5 | Stored analyzer bundles |
| Remaining cases | Synthetic in-memory data |
| Database | In-memory fake Postgres implementation |
| Authentication | Development proxy headers; no analyst login prompt |
| Chat | Stub by default; optional Bedrock, OpenAI-compatible, or local gateway |
| nginx / TLS / DNS | Not required |
| systemd | Not required |

### Existing Documentation And Scripts

```text
DEVELOPING.md
scripts/bootstrap_dev_venv.sh
scripts/bootstrap_dev_venv.ps1
scripts/dev_portal_preview.ps1
scripts/dev_portal_ui.ps1
llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_PREVIEW.md
llm_notable_analysis_onprem_systemd/frontend/analyst-portal/README.md
llm_notable_analysis_onprem_systemd/scripts/preview_portal_ui.py
llm_notable_analysis_onprem_systemd/scripts/preview_fake_db.py
llm_notable_analysis_onprem_systemd/scripts/preview_synthetic_pipeline.py
llm_notable_analysis_onprem_systemd/scripts/preview_knowledge_base.py
```

### Prerequisites

- Git checkout of this repository.
- Python 3.12 or newer.
- Network access during the first bootstrap for Python, Node, and npm packages,
  unless an offline development bundle has already been prepared.
- No root access is required when Python 3.12 is already installed.

### Linux Or WSL Installation

From the repository root:

```bash
bash scripts/bootstrap_dev_venv.sh --skip-playwright-install
source .venv/bin/activate
```

`--skip-playwright-install` avoids downloading the E2E browser when the goal is
only to run the portal locally. Add `--install-python` when using a supported
Linux host that does not already have Python 3.12.

### Windows Installation

From PowerShell at the repository root:

```powershell
.\scripts\bootstrap_dev_venv.ps1
.\.venv\Scripts\Activate.ps1
```

The PowerShell bootstrap currently includes the normal frontend and Playwright
setup. The Linux script exposes the narrower skip flags.

### Start The Preview

Use two terminals from the repository root.

Terminal 1, preview API:

```bash
source .venv/bin/activate
python llm_notable_analysis_onprem_systemd/scripts/preview_portal_ui.py
```

Windows equivalent:

```powershell
.\scripts\dev_portal_preview.ps1
```

Terminal 2, React UI:

```bash
source .venv/bin/activate
npm --prefix llm_notable_analysis_onprem_systemd/frontend/analyst-portal run dev
```

Windows equivalent:

```powershell
.\scripts\dev_portal_ui.ps1
```

Open:

```text
http://127.0.0.1:5173
```

Use `127.0.0.1`, not a DNS name. The Vite server proxies API calls to
`127.0.0.1:8765` and injects the development-only user and proxy-secret headers.

### No-Credential Chat

Do not create `config.portal-preview.env` when external chat is unnecessary.
The preview uses the stub synthesizer and requires no model credential.

### Optional Local LLM Chat

The preview accepts an OpenAI-compatible API URL. To use a LiteLLM or vLLM
gateway already running on the same machine, copy:

```text
llm_notable_analysis_onprem_systemd/config.portal-preview.env.example
```

to:

```text
llm_notable_analysis_onprem_systemd/config.portal-preview.env
```

Remove or comment the Bedrock settings, then set values appropriate to the local
gateway:

```ini
PORTAL_PREVIEW_OPENAI_API_KEY=<local-gateway-token>
PORTAL_PREVIEW_OPENAI_MODEL=<served-model-name>
PORTAL_PREVIEW_OPENAI_API_URL=http://127.0.0.1:4000/v1/chat/completions
```

The config file is gitignored. Do not commit tokens. When the local gateway does
not require authentication, keep the stub preview rather than inventing a
production credential contract for the demo.

### Preview Validation

With the API running:

```bash
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:8765/ready
```

In the browser:

1. Open `http://127.0.0.1:5173`.
2. Confirm the case list loads.
3. Open one of cases 1-5 and review the stored analysis.
4. Send a chat message and confirm a stub or configured-provider response.
5. Confirm no login, DNS, TLS, nginx, or firewall work was required.

### Preview Limitations

- It is a development preview, not a production security boundary.
- Most case data is stored or synthetic.
- PostgreSQL persistence is not exercised.
- The production file-drop analyzer is not running by default.
- Real local alert analysis is not provided by the default stub configuration.
- The preview must remain bound to loopback.

## Option 2: Real Local Analyzer Services

Use this option when the next goal is to validate local inference and real
file-drop analysis without deploying the analyst portal.

The standard installer creates this loopback chain:

```text
notable-analyzer.service
  -> LiteLLM at 127.0.0.1:4000
  -> vLLM at 127.0.0.1:8000
```

The core analyzer does not require DNS, nginx, TLS, PostgreSQL, or analyst
authentication.

Existing documentation and scripts:

```text
llm_notable_analysis_onprem_systemd/docs/operations/deployment/INSTALL.md
llm_notable_analysis_onprem_systemd/docs/operations/deployment/OFFLINE_PRESTAGE_GUIDE.md
llm_notable_analysis_onprem_systemd/docs/operations/deployment/AIRGAPPED_DEPLOYMENT.md
llm_notable_analysis_onprem_systemd/scripts/install.sh
llm_notable_analysis_onprem_systemd/scripts/smoke_service_chain.sh
```

Install from the on-prem package directory:

```bash
cd llm_notable_analysis_onprem_systemd
sudo bash scripts/install.sh
```

Keep the initial capability scope narrow:

```ini
CAPABILITY_PROFILES=core
```

Primary runtime configuration:

```text
/etc/notable-analyzer/config.env
/etc/litellm/config.yaml
```

Required local model path by default:

```text
/opt/models/gemma-4-31B-it
```

Validation:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS \
  -H "Authorization: Bearer <LLM_API_TOKEN>" \
  http://127.0.0.1:4000/v1/models
sudo bash scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env
```

Use the local token already configured in `/etc/notable-analyzer/config.env`;
do not place a real token in this document or source control.

This is a real host install: it requires root access, systemd, model weights,
and the GPU/runtime prerequisites described in the deployment documents.

## Option 3: Real Portal On Localhost

The repository contains the required components, but it does not currently
provide one dedicated `install_localhost_full_stack.sh` workflow for:

```text
real vLLM
+ real analyzer
+ real PostgreSQL portal
+ localhost browser
+ no nginx, TLS, or production authentication
```

The production-shaped portal installer is:

```bash
cd llm_notable_analysis_onprem_systemd
sudo INSTALL_ANALYST_PORTAL=true bash scripts/install.sh
```

That path installs PostgreSQL, pgvector, nginx assets, the portal service, and
the React build. It still expects operators to provide production TLS, nginx
hostname configuration, and analyst authentication before network exposure.

For a localhost-only engineering exercise, the portal service can remain on
`127.0.0.1:8080` and the Vite development server can proxy to it. The Vite
settings are:

```text
VITE_PORTAL_API_TARGET=http://127.0.0.1:8080
VITE_PORTAL_DEV_USER=<development-user>
VITE_PORTAL_DEV_PROXY_SECRET=<must-match-PORTAL_PROXY_SECRET>
```

The matching portal value is stored in:

```text
/etc/notable-analyzer/portal.env
```

This avoids DNS, TLS, nginx Basic Auth, and a production login prompt while
preserving the portal application's proxy-header checks. It is a development
configuration only. Do not expose ports `5173` or `8080` beyond loopback.

Supporting paths:

```text
llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md
llm_notable_analysis_onprem_systemd/frontend/analyst-portal/README.md
llm_notable_analysis_onprem_systemd/frontend/analyst-portal/vite.config.ts
llm_notable_analysis_onprem_systemd/config.portal.env.example
```

## Rollout Sequence

### Phase 1: Localhost Preview

- Bootstrap the repo `.venv`.
- Start the preview API and Vite UI.
- Use stub chat.
- Demonstrate case browsing and chat at `127.0.0.1:5173`.
- Record functional feedback without introducing production infrastructure.

### Phase 2: Real Local Analyzer

- Stage the approved local model.
- Install vLLM, LiteLLM, and the analyzer.
- Keep `CAPABILITY_PROFILES=core`.
- Run a real file-drop smoke test.
- Confirm all service listeners remain on loopback.

### Phase 3: Real Local Portal, Only If Needed

- Install PostgreSQL and the portal.
- Keep the API on `127.0.0.1:8080`.
- Use the Vite development proxy and development-only headers.
- Validate real case archive and local chat behavior.

### Phase 4: Production SCIF Rollout

Only after the localhost workflow is accepted:

- Replace Vite with the built static portal served through nginx.
- Add the approved internal hostname and DNS record.
- Add trusted TLS.
- Add named analyst authentication and account lifecycle procedures.
- Apply firewall restrictions.
- Enable production retention, backup, monitoring, and log forwarding.
- Enable optional integrations one profile at a time.

Production rollout references:

```text
llm_notable_analysis_onprem_systemd/docs/operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md
llm_notable_analysis_onprem_systemd/docs/operations/security/SECURITY_OPERATIONS.md
llm_notable_analysis_onprem_systemd/docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md
llm_notable_analysis_onprem_systemd/docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md
```

## Current Recommendation

For the current request, use Option 1. It is already documented and supported
by the repository, it requires no production infrastructure decisions, and it
provides the shortest path to a localhost demonstration.

Use Option 2 only when real local inference and file-drop processing must be
validated. Do not start Option 3 or the production SCIF rollout merely to show
the current UI and workflow.
