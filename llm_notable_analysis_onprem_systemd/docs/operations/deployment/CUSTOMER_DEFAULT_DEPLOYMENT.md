# Customer default deployment (portal + RAG + closed tickets)

Normative **repo templates** (copy to the host):

- `config.env.example` → `/etc/notable-analyzer/config.env` (analyzer)
- `config.portal.env.example` → `/etc/notable-analyzer/portal.env` (portal)

There are only **two runtime env files** on the host. The `.example` files in git are templates, not loaded at runtime.

Optional **hardware-tuned** overlays (same two-file model, different LLM/chat knobs):
`config.env.rtx-pro-6000-blackwell-5analysts.example` and matching `config.portal.env.*` + vLLM drop-in — use when applying the Blackwell profile script, not as a third runtime file.

Capability bundle: `CAPABILITY_PROFILES=core,rag,analyst_portal` on the analyzer;
`core,analyst_portal` on the portal process, plus mirrored RAG/SPL/closed-ticket
flags on `portal.env` (the portal does not inherit analyzer env).

Hardware-specific tuning (vLLM drop-in, chat concurrency) remains in
`config.env.rtx-pro-6000-blackwell-5analysts.example` and the apply script.

## What retrieval does (accuracy)

All KB lanes are **retrieve then inject**:

1. Hybrid search (Postgres FTS + pgvector, RRF fusion, quality gates).
2. Optional **cross-encoder rerank** when `RAG_RERANK_ENABLED=true`.
3. Bounded snippets appended to the LLM prompt as **advisory** context (labeled
   separately from alert/case evidence).

This applies to **first-pass analysis** (general SOC RAG, SPL query RAG,
historical closed tickets) and to **portal chat** (same KB lanes + pinned-case
chunks + optional closed-ticket lane).

## Config checklist (both files)

| Setting | Analyzer | Portal | Notes |
| --- | --- | --- | --- |
| `CAPABILITY_PROFILES` | `core,rag,analyst_portal` | `core,analyst_portal` | Profiles are process-local |
| `RAG_ENABLED` + `RAG_POSTGRES_*` | via `rag` profile | **explicit `true`** | Portal must duplicate RAG DSN/schema |
| `RAG_RERANK_ENABLED` | `true` | `true` | Stage Granite rerank model offline |
| `RAG_EMBEDDING_MODEL` | `ibm-granite/granite-embedding-english-r2` | same | 768-dim; replaces Mixedbread |
| `RAG_RERANK_MODEL` | `ibm-granite/granite-embedding-reranker-english-r2` | same | Apache 2.0 US lineage |
| `RAG_VECTOR_DIMENSIONS` / `CASE_QA_VECTOR_DIMENSIONS` | `768` | `768` | Must match; rebuild indexes on change |
| `SPL_QUERY_RAG_ENABLED` | `true` | `true` | Requires SPL KB ingest |
| `SPL_QUERY_GENERATION_ENABLED` | `true` | n/a | SPL drafts in analysis; no live Splunk without `spl_readonly` |
| `CLOSED_TICKET_RAG_ENABLED` | `true` | `true` | Retrieval after tickets indexed |
| `CASE_QA_CLOSED_TICKET_ENABLED` | `true` | `true` | Chat closed-ticket lane |
| `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED` | `true` when SN ready | n/a | Needs token, HTTPS base URL, encoded query |
| `CLOSED_TICKET_VISION_ENABLED` | `true` | n/a | Image ticket attachments -> Gemma 4 vision; scans -> Tesseract OCR |
| `CASE_QA_CHAT_HISTORY_ENABLED` | `true` | `true` | Match retention days |
| `CASE_QA_CHAT_IMAGES_ENABLED` | n/a | `true` | Request-scoped chat images; requires multimodal Gemma |
| `PORTAL_PROXY_SECRET` | same value | same value | nginx → portal |

## Beyond config (required for on-prem)

1. **Install stack** — `scripts/install.sh`, LiteLLM/vLLM, Postgres, systemd units
   ([`INSTALL.md`](INSTALL.md)).
2. **Postgres** — `scripts/setup_postgres_rag.sh` (general SOC KB + `--spl-query-rag`),
   `scripts/setup_postgres_case_archive.sh` (cases, chat tables, closed-ticket schema
   + portal SELECT grants).
3. **KB content** — Customer-owned source docs; ingest/rebuild per
   [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md)
   (general + SPL corpora).
4. **Closed tickets** — Configure ServiceNow read-only sync; enable
   `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED`; install and enable
   `notable-closed-ticket-sync.timer`; set `CLOSED_TICKET_VISION_ENABLED=true`
   (or run `scripts/configure_closed_ticket_vision_defaults.sh`) when ticket
   attachments include screenshots; verify chunks in
   `notable_closed_tickets.ticket_chunks` ([`../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md)).
5. **Offline models** — Granite embed + rerank weights and image-ingest bundle
   (Tesseract, pypdfium2, Pillow) under `HF_HOME` / bundle install when air-gapped
   ([`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md),
   [`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md)).
6. **Portal network** — nginx TLS, Basic Auth, DNS/firewall
   ([`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)).
7. **SOAR file drop** — SFTP ownership/permissions on `INCOMING_DIR`.
8. **Smoke** — `scripts/smoke_service_chain.sh`, `scripts/smoke_postgres_rag.sh`,
   one notable → portal case, chat with KB + closed-ticket questions after sync.

No additional application code changes are required when the above data plane
and env mirror are in place.
