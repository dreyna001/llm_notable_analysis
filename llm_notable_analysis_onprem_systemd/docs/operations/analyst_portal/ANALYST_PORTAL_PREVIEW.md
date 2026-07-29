# Analyst portal local preview

Run the analyst portal UI on a developer workstation **without** production
Postgres, nginx, or the on-prem analyzer LLM. Preview uses in-memory fake data
for cases 6-55 and **stored analyzer bundles** for cases 1-5. When Bedrock is
configured, it also accepts local file drops and publishes their real analysis
to the live preview case store.

Bedrock preview mode uses direct Bedrock calls for both newly dropped alerts and
chatbot synthesis. OpenAI and stub modes support chatbot synthesis only.

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
| Local file drop | With Bedrock configured, watches `wsl-notable-data/incoming/` for top-level `.json` and `.txt`; completed cases appear in the live case list |
| Case analysis on page load | Read from bundles only; no analyzer LLM |
| Chatbot | Live Bedrock / OpenAI / stub via `config.portal-preview.env`; Bedrock uses production prompt assembly via `chat_text_complete` |
| Chat history / sessions | Enabled in preview by default (`CASE_QA_CHAT_HISTORY_ENABLED=true`); multi-turn chat with persisted sessions on the in-memory fake Postgres connection |
| Knowledge Base (chat) | Committed fixtures in `data/preview_scenarios/knowledge_base/`; keyword-matched advisory snippets injected on `/api/chat` (same `knowledge_base` lane as production; **no Postgres RAG, no Bedrock KB, no S3 Vectors**) |
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
- `preview_bedrock_llm.py` — preview Bedrock credentials and Converse transport
- `preview_file_drop.py` — local polling plus the shared Bedrock analyzer
- `preview_env.py` — loads `config.portal-preview.env`
- `preview_synthetic_pipeline.py` — loads stored bundles for cases 1-5
- `preview_knowledge_base.py` — synthetic KB fixtures for preview chat
- `write_preview_bundles.py` — regenerate bundles from `preview_stored_analysis.py` (no live analyzer LLM)
- `generate_preview_scenarios.py` — optional live analyzer regeneration

Fixture layout: [`data/preview_scenarios/README.md`](../../../data/preview_scenarios/README.md).

**Preview demo KB posture:** use the committed fixture docs above for Knowledge
Base demos. Do **not** provision Amazon Bedrock Knowledge Base, S3 Vectors, or
OpenSearch for local preview. Bedrock provides alert analysis and chat
synthesis; preview KB grounding still comes from committed fixtures.
AWS production KB setup is documented in
[`s3_notable_pipeline/docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](../../../../s3_notable_pipeline/docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md).

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

### 3. AWS SSO login (Bedrock analysis and chat)

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

### Drop a new alert for real Bedrock analysis

With the Bedrock settings above configured, copy a top-level `.json` or `.txt`
file into:

```text
llm_notable_analysis_onprem_systemd/wsl-notable-data/incoming/
```

The preview API polls every two seconds by default. A successful input moves to
`processed/`, its markdown report is written to `reports/`, and its case appears
in the portal. Invalid input or analysis failures move to `quarantine/`.

Override the root with `PORTAL_PREVIEW_FILE_DROP_ROOT`, change polling with
`PORTAL_PREVIEW_FILE_DROP_POLL_INTERVAL`, or disable the worker with
`PORTAL_PREVIEW_FILE_DROP_ENABLED=false`.

## What to exercise

| URL / area | Purpose |
|------------|---------|
| `/cases` | Case list (55 cases, paginated) |
| `/cases/case-1` ... `/cases/case-5` | Full stored analysis panels |
| Case chat | Live Bedrock/OpenAI synthesis with multi-turn sessions (selected-case mode recommended) |

### Knowledge Base demo (alert 5 / case-5)

Step-by-step walkthrough, copy-paste demo questions, and troubleshooting:
[`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](../../../../PREVIEW_CASE_INVESTIGATION_GUIDE.md#how-to-demo-knowledge-base-on-alert-5-case-5)
(repo root).

Fixtures: `data/preview_scenarios/knowledge_base/`.

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
