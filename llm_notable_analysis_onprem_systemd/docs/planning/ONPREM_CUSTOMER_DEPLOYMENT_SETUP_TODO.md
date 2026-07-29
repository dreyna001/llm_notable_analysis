# On-Prem Customer Deployment Setup TODO

Tracks customer-host bring-up beyond first `scripts/install.sh`: env templates,
Postgres data plane, KB ingest, retrieval models, and installer automation gaps.

Related:

- [`CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md)
- [`HOST_LAYOUT_AND_UPDATES.md`](../operations/deployment/HOST_LAYOUT_AND_UPDATES.md)
- [`ONPREM_PRODUCTION_READINESS_TODO.md`](ONPREM_PRODUCTION_READINESS_TODO.md)

## Customer host: auroraaihost (in progress)

| Step | Status | Notes |
| --- | --- | --- |
| Git checkout at `/opt/src/llm_notable_analysis` | Done | At `fa722fc` (2026-07-29) |
| Runtime `/opt/notable-analyzer` synced from checkout | Done | `install.sh` run |
| Customer-default merge into `/etc/notable-analyzer/*.env` | Done | Sanity: core keys OK; optional integration tokens empty |
| Dirs: KB source, SPL source, closed-ticket attachments | Done | |
| Embed cache `granite-embedding-english-r2` (768-dim) | Open | Replaces prior Mixedbread cache |
| Rerank cache `granite-embedding-reranker-english-r2` | Open | Stage when enabling rerank offline |
| Postgres RAG + closed-ticket schemas/tables | Done | Chunk counts 0 until KB/SN data |
| KB source file content | Open | Customer corpus not loaded yet |
| Service restart + smoke | Open | After operator sign-off |

## Owner actions (not automated)

- [ ] **Ticketing / closed-ticket sync (operator: Dreyn)** — Confirm which system the customer uses (ServiceNow or other). Configure read-only sync credentials, encoded query, and `SERVICENOW_CLOSED_TICKET_*` (or future adapter) on the analyzer `config.env`; enable `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true`; enable `notable-closed-ticket-sync.timer`. Required for closed-ticket RAG in **analysis** and **portal chat**. See [`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md).

## Immediate blockers (auroraaihost)

1. [x] Set working `RAG_POSTGRES_DSN` (and `CASE_POSTGRES_DSN` / portal DSNs).
2. [x] `git pull origin main` on `/opt/src/llm_notable_analysis`.
3. [x] Merge customer-default env from main examples.
4. [x] Re-run `setup_postgres_rag.sh` (general + `--spl-query-rag`).
5. [x] Re-run `setup_postgres_case_archive.sh`.
6. [ ] Stage Granite embed/rerank models if `RAG_RERANK_ENABLED=true` (768-dim).
7. [ ] `configure_us_granite_retrieval_defaults.sh` on analyzer + portal env (or merge Granite keys).
8. [ ] Build + transfer image-ingest offline bundle; `install_image_ingest_prerequisites.sh` on target.
9. [ ] `verify_image_ingest_prerequisites.sh` passes.
10. [ ] `configure_closed_ticket_vision_defaults.sh` (or merge `CLOSED_TICKET_VISION_ENABLED=true`).
11. [ ] Load customer KB/SPL into source dirs (.txt/.docx); re-run ingest.
12. [ ] `systemctl restart` + smoke (chain + optional vision curl + image-ingest verify).

## Customer-default checklist (from main templates)

Two runtime env files only:

- [ ] `/etc/notable-analyzer/config.env` from `config.env.example` (merge, do not blind overwrite)
- [ ] `/etc/notable-analyzer/portal.env` from `config.portal.env.example` (merge)

Post-config (see [`CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md)):

- [ ] `setup_postgres_rag.sh` (+ `--spl-query-rag`)
- [ ] `setup_postgres_case_archive.sh`
- [ ] KB corpora ingested
- [ ] ServiceNow closed-ticket sync when approved
- [ ] Offline Granite embed/rerank weights + image-ingest bundle when air-gapped
  ([`IMAGE_INGEST_PREREQUISITES.md`](../operations/rag/IMAGE_INGEST_PREREQUISITES.md))
- [ ] Portal TLS, Basic Auth, smoke tests

## `install.sh` automation backlog

Items operators currently run manually; candidates for `install.sh` flags or `scripts/customer_default_postinstall.sh`:

1. [ ] Create `/opt/llm-notable-analysis/knowledge_base/source_docs`, `spl_query_source_docs`, index dirs; ownership `notable-analyzer`.
2. [ ] Create `CLOSED_TICKET_ATTACHMENT_DIR` (default under `/var/notables/closed_ticket_attachments`).
3. [ ] Optional `SETUP_POSTGRES_RAG=true`: run `setup_postgres_rag.sh` and `--spl-query-rag` when Postgres + config env exist.
4. [ ] Run `setup_postgres_case_archive.sh` when portal/case archive is in scope (not only behind `INSTALL_ANALYST_PORTAL=true`), or document explicit flag.
5. [ ] Optional `STAGE_RETRIEVAL_MODELS=true`: pre-download Granite embed/rerank models into cache dirs (today `MODEL_DOWNLOAD` is LLM gemma only).
6. [ ] Optional image-ingest bundle install hook (`install_image_ingest_prerequisites.sh`) behind install flag.
7. [ ] Optional `APPLY_CUSTOMER_DEFAULT_ENV=true`: upsert from both `.example` files without wiping live secrets/DSNs.
8. [ ] Optional `VLLM_PROFILE=rtx-pro-6000-blackwell-5analysts`: install vLLM drop-in only (do not reuse full `apply_rtx_*` env map that omits `rag` profile).
9. [ ] Validate `RAG_POSTGRES_DSN` / `CASE_POSTGRES_DSN` can connect before ingest (clear error if password missing under password auth).
10. [ ] Document merge order: customer-default env first, then hardware overlay keys.

## Wrapper script (planned)

- [ ] Add `scripts/customer_default_postinstall.sh` orchestrating: dirs, env merge, optional RTX vLLM drop-in, Postgres setup scripts, optional model staging, smoke hint (no secrets in repo).
