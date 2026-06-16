# Analyst portal local preview

Run the analyst portal UI on a developer workstation **without** production
Postgres, nginx, or the on-prem analyzer LLM. Preview uses in-memory fake data
for cases 6-55 and **stored analyzer bundles** for cases 1-5.

Only the **chatbot** may call a live LLM (Bedrock, OpenAI, or stub text).

Production portal deployment is documented in
[`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md). Shared dev
venv setup is in [`DEVELOPING.md`](../../../DEVELOPING.md).

Case investigation question flows for preview scenarios are in
[`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md)
(repo root).

## What preview includes

| Component | Preview behavior |
|-----------|------------------|
| Cases 1-5 | Stored alert + analysis from `data/preview_scenarios/bundles/` |
| Cases 6-55 | Lightweight in-memory list fillers (pagination) |
| Case analysis on page load | Read from bundles only; no analyzer LLM |
| Chatbot | Live Bedrock / OpenAI / stub via `config.portal-preview.env` |
| Postgres / nginx / systemd | Not required |

Preview scripts live under `scripts/` at the **monorepo root** (not under this
package alone):

- `scripts/bootstrap_dev_venv.ps1` / `bootstrap_dev_venv.sh`
- `scripts/dev_portal_preview.ps1`
- `scripts/dev_portal_ui.ps1`

Python preview modules live in `llm_notable_analysis_onprem_systemd/scripts/`:

- `preview_portal_ui.py` — preview API (port 8765)
- `preview_bedrock_llm.py` — Bedrock Converse chat (preview only)
- `preview_env.py` — loads `config.portal-preview.env`
- `preview_synthetic_pipeline.py` — loads stored bundles
- `write_preview_bundles.py` — regenerate bundles without a live analyzer LLM

## Prerequisites

- Git checkout on branch `feature/portal-bedrock-llm` (or main once merged)
- Python **3.12+**
- Network for first bootstrap (pip, nodeenv, npm)
- For Bedrock chat: AWS CLI with SSO profile and Bedrock model access

## One-time setup

### 1. Clone and checkout

```powershell
cd C:\path\to\llm_notable_analysis
git fetch origin
git checkout feature/portal-bedrock-llm
git pull origin feature/portal-bedrock-llm
```

### 2. Bootstrap shared dev environment

From the **repo root**:

```powershell
.\scripts\bootstrap_dev_venv.ps1
.\.venv\Scripts\Activate.ps1
```

Linux:

```bash
bash scripts/bootstrap_dev_venv.sh
source .venv/bin/activate
```

### 3. Install Bedrock dependency

Bootstrap does **not** install `boto3` automatically. With the venv active:

```powershell
pip install boto3==1.37.38
```

Or install from the package requirements file:

```powershell
pip install -r llm_notable_analysis_onprem_systemd\requirements.txt
```

### 4. Create preview chat config

Copy the example file (or paste its contents into a new file):

```powershell
Copy-Item llm_notable_analysis_onprem_systemd\config.portal-preview.env.example llm_notable_analysis_onprem_systemd\config.portal-preview.env
```

Edit `llm_notable_analysis_onprem_systemd\config.portal-preview.env`. For
Bedrock in `us-east-1` with Claude Sonnet 4.6:

```ini
PORTAL_LLM_PROVIDER=bedrock
PORTAL_PREVIEW_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
PORTAL_PREVIEW_BEDROCK_AWS_PROFILE=your-sso-profile-name
AWS_REGION=us-east-1
```

Notes:

- This file is **gitignored**; only the `.example` is committed.
- You do **not** need `config.portal.env` for preview.
- The preview env file is small (~19 lines); Bedrock fields are enough when
  using Bedrock chat.

### 5. AWS SSO login (Bedrock chat only)

```powershell
aws sso login --profile your-sso-profile-name
```

## Daily workflow

Use **two terminals** from the repo root with the venv activated.

**Terminal 1 — preview API** (http://127.0.0.1:8765):

```powershell
.\scripts\dev_portal_preview.ps1
```

Confirm startup output includes:

```text
Chat synthesis: Bedrock (us.anthropic.claude-sonnet-4-6, profile=your-sso-profile-name)
Pipeline-backed analyzer cases: case-1 .. case-5
```

**Terminal 2 — React UI** (http://127.0.0.1:5173):

```powershell
.\scripts\dev_portal_ui.ps1
```

Open **http://127.0.0.1:5173** in the browser. Use `127.0.0.1`, not `localhost`,
if Vite is bound to `127.0.0.1` only.

## What to exercise

| URL / area | Purpose |
|------------|---------|
| `/cases` | Case list (55 cases, paginated) |
| `/cases/case-1` ... `/cases/case-5` | Full stored analysis panels |
| Case chat | Live Bedrock synthesis (selected-case mode recommended) |

See [`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md)
for recommended analyst questions on case 1.

## Optional chat providers

**OpenAI** (instead of Bedrock) in `config.portal-preview.env`:

```ini
PORTAL_LLM_PROVIDER=local
PORTAL_PREVIEW_OPENAI_API_KEY=sk-...
PORTAL_PREVIEW_OPENAI_MODEL=gpt-4.1-mini
```

**Stub chat** (no external LLM): leave Bedrock and OpenAI unset. Chat returns
placeholder preview text.

## Health checks

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health

.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\preview_portal_ui.py --verify-auth
```

## Regenerating stored analysis (cases 1-5)

Bundles are committed artifacts. To refresh after editing alerts or stored
analysis content:

```powershell
.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\write_preview_bundles.py
```

Optional: regenerate via live analyzer LLM (`LLM_API_URL` required):

```powershell
.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\generate_preview_scenarios.py --overwrite
```

See also [`data/preview_scenarios/README.md`](../../data/preview_scenarios/README.md).

## Troubleshooting

### "Case chat is unavailable: LLM gateway is down"

Preview enables chat, but the capabilities check used to ping the local LLM at
`127.0.0.1:4000` even when Bedrock was configured. Pull branch commit
`1547a9a` or later and restart the preview API.

Also confirm startup shows `Chat synthesis: Bedrock (...)` not `stub (...)`.

### 403 "Cross-site portal write requests are not allowed"

Chat uses `POST /api/chat`. The Vite dev proxy must preserve the browser
`Host` header so it matches `Origin`. Pull commit `ccb07dc` or later and
**restart both** preview API and Vite dev server.

Always browse via **http://127.0.0.1:5173**, not the raw API port.

### `ModuleNotFoundError: No module named 'boto3'`

```powershell
pip install boto3==1.37.38
```

### Bedrock access denied

- Confirm `aws sso login --profile ...` succeeded.
- Confirm model access for Sonnet 4.6 in the Bedrock console.
- List inference profiles:

```powershell
aws bedrock list-inference-profiles --region us-east-1 --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'sonnet-4-6')].inferenceProfileId" --output text --profile your-sso-profile-name
```

### Preview config not loading

File must be named `config.portal-preview.env` (not `.example`) at:

`llm_notable_analysis_onprem_systemd/config.portal-preview.env`

Override path with env var `PORTAL_PREVIEW_ENV` if needed.

## Related docs

- [`frontend/analyst-portal/README.md`](../../frontend/analyst-portal/README.md) — UI dev details, E2E
- [`ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) — production network rollout
- [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md) — production portal day-two ops
- [`DEVELOPING.md`](../../../DEVELOPING.md) — shared venv and daily dev workflow
