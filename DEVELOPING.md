# Local development environment

Use **one shared virtual environment** at the repository root for Python backend
work and for Node/npm (via `nodeenv`). Do not create separate `.venv` folders
under individual packages for day-to-day development.

## Prerequisites

- Python **3.12+** on `PATH` (bootstrap prefers `python3.12` automatically)
- On Linux VMs without Python 3.12, use `bash scripts/bootstrap_dev_venv.sh --install-python`
  or run `bash scripts/install_python312.sh` first
- Network access for the first bootstrap (pip and nodeenv download Node)
- Stop other Python dev servers (for example `preview_portal_ui.py` on port 8765) before
  bootstrap if pip reports `WinError 32` file-in-use errors. OneDrive-synced repo paths
  can also lock files briefly during install.

## Bootstrap (once per machine)

### Windows (PowerShell)

```powershell
Set-Location <repo-root>
.\scripts\bootstrap_dev_venv.ps1
.\.venv\Scripts\Activate.ps1
```

### Linux / macOS

```bash
cd <repo-root>
bash scripts/bootstrap_dev_venv.sh --install-python   # Linux VM without python3.12 yet
# or, if python3.12 is already installed:
bash scripts/bootstrap_dev_venv.sh
source .venv/bin/activate
```

If bootstrap fails with a Python 3.10 venv error, remove the old environment and
re-run (updated bootstrap auto-recreates stale `.venv` directories):

```bash
rm -rf .venv
bash scripts/bootstrap_dev_venv.sh --install-python
```

This installs editable copies of:

- `onprem-llm-sdk`
- `onprem_rag_notable_analysis`
- `llm_notable_analysis_onprem_systemd`

It also installs `pytest`, embeds **Node.js 22** into `.venv` with `nodeenv`, runs
`npm install` for `llm_notable_analysis_onprem_systemd/frontend/analyst-portal`, and
downloads **Playwright Chromium** for portal E2E tests.

Do **not** copy `.venv` from Windows to a Linux VM (or vice versa). Sync the repo
with git, then run `bootstrap_dev_venv.sh` on the VM so Node, npm, Playwright, and
browser binaries match that OS.

Production host paths (`/opt/notable-analyzer`, `/var/notables`, Postgres, nginx)
are documented in the package
[`Filesystem map`](llm_notable_analysis_onprem_systemd/README.md#filesystem-map).
Local dev uses this repo-root `.venv` only — not `/opt/notable-analyzer/venv`.

## Daily workflow

Always activate the root venv first:

```powershell
.\.venv\Scripts\Activate.ps1
```

```bash
source .venv/bin/activate
```

Then use `python` / `pip` / `pytest` / `npm` from that environment.

### Analyst portal (API + React UI)

Terminal 1 — portal API preview (fake Postgres data):

```powershell
.\scripts\dev_portal_preview.ps1
```

```bash
python llm_notable_analysis_onprem_systemd/scripts/preview_portal_ui.py
```

Terminal 2 — React dev server:

```powershell
.\scripts\dev_portal_ui.ps1
```

```bash
npm --prefix llm_notable_analysis_onprem_systemd/frontend/analyst-portal run dev
```

Open http://127.0.0.1:5173/ (UI) with the API on http://127.0.0.1:8765/.

Full preview setup (Bedrock chat, stored cases 1-5, troubleshooting) is in
[`llm_notable_analysis_onprem_systemd/docs/operations/ANALYST_PORTAL_PREVIEW.md`](llm_notable_analysis_onprem_systemd/docs/operations/ANALYST_PORTAL_PREVIEW.md).

Recommended analyst questions for preview case investigation are in
[`PREVIEW_CASE_INVESTIGATION_GUIDE.md`](PREVIEW_CASE_INVESTIGATION_GUIDE.md).

After bootstrap, install Bedrock support for preview chat:

```powershell
pip install boto3==1.37.38
```

### Portal E2E (Playwright)

Bootstrap installs `@playwright/test` under the analyst-portal frontend and
downloads Chromium into your user cache (`%USERPROFILE%\AppData\Local\ms-playwright`
on Windows, `~/.cache/ms-playwright` on Linux).

Always use npm from the repo `.venv` (wrapper scripts set `PATH` for you):

Windows (local, with SSH tunnel to VM on 8443 if testing deployed portal):

```powershell
$env:PORTAL_E2E_BASE_URL = "https://127.0.0.1:8443"
$env:PORTAL_E2E_USER = "analyst"
$env:PORTAL_E2E_PASSWORD = "analyst-lab-change-me"
.\scripts\dev_portal_e2e.ps1
```

Linux VM (after `git pull` and fresh bootstrap on that machine):

```bash
bash scripts/bootstrap_dev_venv.sh
source .venv/bin/activate
PORTAL_E2E_BASE_URL=https://127.0.0.1:8443 \
PORTAL_E2E_USER=analyst \
PORTAL_E2E_PASSWORD=analyst-lab-change-me \
bash scripts/dev_portal_e2e.sh
```

Re-download browsers only: `.\scripts\dev_portal_e2e.ps1 -InstallBrowsers` or
`bash scripts/dev_portal_e2e.sh --install-browsers`.

See [`frontend/analyst-portal/README.md`](llm_notable_analysis_onprem_systemd/frontend/analyst-portal/README.md)
for `PORTAL_E2E_*` variables.

### Tests

From the repo root with the venv activated:

```bash
pytest llm_notable_analysis_onprem_systemd/tests/onprem_service -q
```

See also [`llm_notable_analysis_onprem_systemd/docs/testing/TESTING.md`](llm_notable_analysis_onprem_systemd/docs/testing/TESTING.md).

## IDE

Point your Python interpreter at:

- Windows: `<repo-root>/.venv/Scripts/python.exe`
- Unix: `<repo-root>/.venv/bin/python`
