# Local development environment

Use **one shared virtual environment** at the repository root for Python backend
work and for Node/npm (via `nodeenv`). Do not create separate `.venv` folders
under individual packages for day-to-day development.

## Prerequisites

- Python **3.12+** on `PATH` (or pass `--Python py -3.12` to the bootstrap script)
- Network access for the first bootstrap (pip and nodeenv download Node)
- Stop other Python dev servers (for example `preview_portal_ui.py` on port 8765) before
  bootstrap if pip reports `WinError 32` file-in-use errors. OneDrive-synced repo paths
  can also lock files briefly during install.

Production hosts still use `/opt/notable-analyzer/venv`; that is separate from
this local dev layout.

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
bash scripts/bootstrap_dev_venv.sh
source .venv/bin/activate
```

This installs editable copies of:

- `onprem-llm-sdk`
- `onprem_rag_notable_analysis`
- `llm_notable_analysis_onprem_systemd`

It also installs `pytest`, embeds **Node.js 22** into `.venv` with `nodeenv`, and
runs `npm install` for `llm_notable_analysis_onprem_systemd/frontend/analyst-portal`.

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
