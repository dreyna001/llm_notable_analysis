# Customer default deployment (portal + RAG + closed tickets)

Normative **example env** pair for portal-first customer go-live:

- `config.env.example` → `/etc/notable-analyzer/config.env`
- `config.portal.env.example` → `/etc/notable-analyzer/portal.env`

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
| `RAG_RERANK_ENABLED` | `true` | `true` | Stage rerank model offline |
| `SPL_QUERY_RAG_ENABLED` | `true` | `true` | Requires SPL KB ingest |
| `SPL_QUERY_GENERATION_ENABLED` | `true` | n/a | SPL drafts in analysis; no live Splunk without `spl_readonly` |
| `CLOSED_TICKET_RAG_ENABLED` | `true` | `true` | Retrieval after tickets indexed |
| `CASE_QA_CLOSED_TICKET_ENABLED` | `true` | `true` | Chat closed-ticket lane |
| `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED` | `true` when SN ready | n/a | Needs token, HTTPS base URL, encoded query |
| `CASE_QA_CHAT_HISTORY_ENABLED` | `true` | `true` | Match retention days |
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
   `notable-closed-ticket-sync.timer`; verify chunks in
   `notable_closed_tickets.ticket_chunks` ([`../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md)).
5. **Offline models** — Embedding + rerank weights under `HF_HOME` /
   `SENTENCE_TRANSFORMERS_HOME` when air-gapped ([`OFFLINE_PRESTAGE_GUIDE.md`](OFFLINE_PRESTAGE_GUIDE.md)).
6. **Portal network** — nginx TLS, Basic Auth, DNS/firewall
   ([`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)).
7. **SOAR file drop** — SFTP ownership/permissions on `INCOMING_DIR`.
8. **Smoke** — `scripts/smoke_service_chain.sh`, `scripts/smoke_postgres_rag.sh`,
   one notable → portal case, chat with KB + closed-ticket questions after sync.

No additional application code changes are required when the above data plane
and env mirror are in place.
