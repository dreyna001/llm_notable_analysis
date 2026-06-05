# Analyst Portal UI (React)

Minimal React + Vite + Tailwind + shadcn-style UI for the read-only analyst portal APIs.

Security, SSO, and production static hosting are out of scope for this spike.

## Prerequisites

- Shared repo virtualenv at `<repo-root>/.venv` (see [`DEVELOPING.md`](../../../DEVELOPING.md))
- Portal API running locally (preview script or real `portal_app`)

Node and npm come from that venv (`nodeenv`), not a separate system install.

## Quick start

From the **repository root**, bootstrap once if you have not already:

```powershell
.\scripts\bootstrap_dev_venv.ps1
.\.venv\Scripts\Activate.ps1
```

Live OpenAI-backed chat in the preview API (local dev only):

1. Edit `llm_notable_analysis_onprem_systemd/config.portal-preview.env`
2. Set `PORTAL_PREVIEW_OPENAI_API_KEY=` to your OpenAI key
3. Restart the preview API terminal after saving

Until the key is set, chat uses the stub synthesizer. Model default is `gpt-4.1-mini`.

Terminal 1 — portal API with fake data:

```powershell
.\scripts\dev_portal_preview.ps1
```

Terminal 2 — React dev server:

```powershell
.\scripts\dev_portal_ui.ps1
```

Open http://127.0.0.1:5173/

The Vite dev server proxies `/api`, `/health`, and `/ready` to `http://127.0.0.1:8765`
and injects dev-only proxy auth headers (`X-Forwarded-User`, portal proxy secret).

## Environment overrides

```text
VITE_PORTAL_API_TARGET=http://127.0.0.1:8080
VITE_PORTAL_DEV_USER=analyst@example.com
VITE_PORTAL_DEV_PROXY_SECRET=portal-secret
```

Preview API OpenAI chat (read by `scripts/preview_portal_ui.py`, not the Vite app):

```text
PORTAL_PREVIEW_OPENAI_API_KEY=sk-...
PORTAL_PREVIEW_OPENAI_MODEL=gpt-4.1-mini
```

Or copy `config.portal-preview.env.example` to `config.portal-preview.env` in
`llm_notable_analysis_onprem_systemd/`.

## Build

With the repo venv activated:

```powershell
npm --prefix llm_notable_analysis_onprem_systemd/frontend/analyst-portal run build
```

Output: `dist/` (static files for later nginx or FastAPI static mount).

## Routes

| Path | Purpose |
|------|---------|
| `/` | Home + API health |
| `/cases` | Paginated case list |
| `/cases/:caseId` | Case detail (JSON inspection) |
