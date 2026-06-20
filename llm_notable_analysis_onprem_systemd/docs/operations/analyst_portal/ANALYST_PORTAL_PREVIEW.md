# Analyst portal local preview

Run the analyst portal UI on a developer workstation **without** production
Postgres, nginx, or the on-prem analyzer LLM. Preview uses in-memory fake data
for cases 6-55 and **stored analyzer bundles** for cases 1-5.

Only the **chatbot** may call a live LLM (Bedrock, OpenAI, or stub text).

Production portal deployment is documented in
[`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md). Shared dev
venv setup is in [`DEVELOPING.md`](../../../../DEVELOPING.md).

Case investigation question flows for preview scenarios are in
[`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md)
(repo root).

## What preview includes

| Component | Preview behavior |
|-----------|------------------|
| Cases 1-5 | Stored alert + analysis from `data/preview_scenarios/bundles/`; loaded via `preview_synthetic_pipeline` (normalization + archive record build; no analyzer LLM) |
| Cases 6-55 | Lightweight in-memory list fillers (pagination; 55 total, page size 50) |
| Case analysis on page load | Read from bundles only; no analyzer LLM |
| Chatbot | Live Bedrock / OpenAI / stub via `config.portal-preview.env`; Bedrock uses production prompt assembly via `chat_text_complete` |
| Chat history / sessions | Enabled in preview by default (`CASE_QA_CHAT_HISTORY_ENABLED=true`); multi-turn chat with persisted sessions on the in-memory fake Postgres connection |
| Postgres / nginx / systemd | Not required |

| Case | Alert type |
|------|------------|
| 1 | Malware Beaconing |
| 2 | Impossible Travel |
| 3 | Suspicious PowerShell |
| 4 | Privilege Escalation Attempt |
| 5 | Suspicious RDP Lateral Movement |

Preview scripts live under `scripts/` at the **monorepo root**:

- `scripts/bootstrap_dev_venv.ps1` / `bootstrap_dev_venv.sh`
- `scripts/dev_portal_preview.ps1`
- `scripts/dev_portal_ui.ps1`

Python preview modules live in `llm_notable_analysis_onprem_systemd/scripts/`:

- `preview_portal_ui.py` — preview API (port 8765)
- `preview_bedrock_llm.py` — Bedrock Converse chat (preview only)
- `preview_env.py` — loads `config.portal-preview.env`
- `preview_synthetic_pipeline.py` — loads stored bundles for cases 1-5
- `write_preview_bundles.py` — regenerate bundles from `preview_stored_analysis.py` (no live analyzer LLM)
- `generate_preview_scenarios.py` — optional live analyzer regeneration

Fixture layout: [`data/preview_scenarios/README.md`](../../../data/preview_scenarios/README.md).

## Prerequisites

- Git checkout of this repo (Python **3.12+**)
- Network for first bootstrap (pip, nodeenv, npm)
- For Bedrock chat: AWS CLI with SSO profile and Bedrock model access

## One-time setup

### 1. Bootstrap shared dev environment

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

See [`DEVELOPING.md`](../../../../DEVELOPING.md) for `--install-python` on Linux VMs
without Python 3.12.

Bootstrap installs `boto3==1.37.38` for Bedrock preview chat. If you created the
venv before that change, run `pip install boto3==1.37.38` once with the venv active.

### 2. Create preview chat config

Copy the example file:

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

- This file is **gitignored**; only `config.portal-preview.env.example` is committed.
- You do **not** need `config.portal.env` for preview.
- Override path with env var `PORTAL_PREVIEW_ENV` if needed.

### 3. AWS SSO login (Bedrock chat only)

```powershell
aws sso login --profile your-sso-profile-name
```

## Daily workflow

Use **two terminals** from the repo root with the venv activated.

**Terminal 1 — preview API** (http://127.0.0.1:8765):

```powershell
.\scripts\dev_portal_preview.ps1
```

```bash
python llm_notable_analysis_onprem_systemd/scripts/preview_portal_ui.py
```

Confirm startup output includes lines like:

```text
Chat synthesis: Bedrock (us.anthropic.claude-sonnet-4-6, profile=your-sso-profile-name)
Preview cases: 55 (paginated at limit 50)
Pipeline-backed analyzer cases: case-1 .. case-5
```

**Terminal 2 — React UI** (http://127.0.0.1:5173):

```powershell
.\scripts\dev_portal_ui.ps1
```

```bash
npm --prefix llm_notable_analysis_onprem_systemd/frontend/analyst-portal run dev
```

Open **http://127.0.0.1:5173** in the browser. Use `127.0.0.1`, not `localhost`,
if Vite is bound to `127.0.0.1` only.

The Vite dev server proxies `/api`, `/health`, and `/ready` to port 8765 and
injects dev proxy auth headers.

## What to exercise

| URL / area | Purpose |
|------------|---------|
| `/cases` | Case list (55 cases, paginated) |
| `/cases/case-1` ... `/cases/case-5` | Full stored analysis panels |
| Case chat | Live Bedrock/OpenAI synthesis with multi-turn sessions (selected-case mode recommended) |

See [`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md)
for recommended analyst questions on case 1.

## Optional chat providers

**OpenAI** (instead of Bedrock): comment out or remove all Bedrock fields from
`config.portal-preview.env` (Bedrock wins when `PORTAL_PREVIEW_BEDROCK_MODEL_ID`
is set). Then set:

```ini
PORTAL_PREVIEW_OPENAI_API_KEY=sk-...
PORTAL_PREVIEW_OPENAI_MODEL=gpt-4.1-mini
```

`OPENAI_API_KEY` is also accepted. Restart the preview API after saving.

**Stub chat** (no external LLM): leave Bedrock and OpenAI unset. Chat returns
placeholder preview text.

## Health and auth checks

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health
Invoke-WebRequest http://127.0.0.1:8765/ready

.\scripts\dev_portal_preview.ps1 --verify-auth
```

In-process proxy-auth contract (no running server). For a full-stack check like
production nginx, start the API with `--no-inject-auth`, run Vite in terminal 2,
then:

```powershell
.\scripts\dev_portal_preview.ps1 --verify-auth-live http://127.0.0.1:8765
```

See [`frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md)
for `PORTAL_PREVIEW_INJECT_AUTH` and Vite proxy overrides.

## Regenerating stored analysis (cases 1-5)

Bundles are committed artifacts. To refresh after editing alerts or stored
analysis content (no live analyzer LLM):

```powershell
.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\write_preview_bundles.py
```

Optional: regenerate via live analyzer LLM (`LLM_API_URL` required):

```powershell
.\.venv\Scripts\python.exe llm_notable_analysis_onprem_systemd\scripts\generate_preview_scenarios.py --overwrite
```

Commit updated `data/preview_scenarios/bundles/` so teammates get the same preview
data without calling the analyzer.

## Troubleshooting

### "Case chat is unavailable: LLM gateway is down"

Preview enables chat, but the capabilities check may ping the local LLM gateway at
`127.0.0.1:4000` when Bedrock/OpenAI preview settings are not loaded. Confirm
startup shows `Chat synthesis: Bedrock (...)` or `OpenAI (...)`, not
`stub (...)`. Restart the preview API after editing `config.portal-preview.env`.

### 403 "Cross-site portal write requests are not allowed"

Chat uses `POST /api/chat`. The Vite dev proxy must preserve the browser
`Host` header so it matches `Origin`. **Restart both** preview API and Vite dev
server. Always browse via **http://127.0.0.1:5173**, not the raw API port.

### `ModuleNotFoundError: No module named 'boto3'`

Re-run bootstrap or install manually: `pip install boto3==1.37.38`

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

## Related docs

- [`frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md) — UI dev details, E2E, proxy auth
- [`ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) — production network rollout
- [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md) — production portal day-two ops
- [`DEVELOPING.md`](../../../../DEVELOPING.md) — shared venv and daily dev workflow
- [`data/preview_scenarios/README.md`](../../../data/preview_scenarios/README.md) — fixture layout and regeneration
