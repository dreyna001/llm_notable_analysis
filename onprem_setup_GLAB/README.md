# GLAB On-Prem Host Setup

Host-only layout for the GLAB single-host deployment.

This directory is the new home for the non-Docker stack discussed for:

- `gpt-oss-120b` on local `vLLM`
- a local `LiteLLM` proxy on the same host
- local retrieval artifacts built with `SQLite` + `FAISS`
- three users calling one OpenAI-compatible endpoint

## Service Topology

```text
3 users / apps
   |
   v
LiteLLM proxy (127.0.0.1:4000)
   |
   v
vLLM (127.0.0.1:8000)

KB rebuild job (oneshot/timer)
   |
   +--> /var/lib/notable-kb/index/kb.sqlite3
   +--> /var/lib/notable-kb/index/kb.faiss
```

## Important Boundaries

- `vLLM` is a long-running `systemd` service.
- `LiteLLM` is a long-running `systemd` service.
- `SQLite` is a file, not a service.
- `FAISS` is a file plus library usage, not a service.
- KB rebuild should run as a `oneshot` service and optional `timer`, not as a daemon.

## Canonical Host Paths

- `/opt/models/gpt-oss-120b`
- `/opt/models/embeddings/all-MiniLM-L6-v2`
- `/opt/vllm`
- `/opt/litellm`
- `/opt/notable-kb`
- `/etc/litellm/config.yaml`
- `/etc/notable-kb/config.env`
- `/var/lib/notable-kb/source`
- `/var/lib/notable-kb/index`

## Repo Layout Under This Directory

- `onprem_vllm_service/`
  - fork target for the host-native `vLLM` package already present at repo root
- `onprem_litellm_service/`
  - new host-native LiteLLM proxy package
- `onprem_kb_indexer/`
  - new host-native KB rebuild job for `SQLite` + `FAISS`

## Current Constraint

Current LiteLLM docs indicate that full virtual-key/user-management flows require a database backend. Until GLAB chooses and pins that backend explicitly, this layout should assume one shared proxy admin/master key rather than silently pretending per-user key issuance is already solved.

## Host deployment runbook

Step-by-step commands for cloning `https://github.com/dreyna001/llm_notable_analysis.git` and bringing up vLLM, LiteLLM, and the KB indexer on one Linux host are in [HOST_DEPLOY_GLAB.md](HOST_DEPLOY_GLAB.md).
