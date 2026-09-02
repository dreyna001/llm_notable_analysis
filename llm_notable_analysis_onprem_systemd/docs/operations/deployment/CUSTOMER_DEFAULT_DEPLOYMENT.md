# Customer default deployment (portal + RAG + closed tickets)

Path B go-live checklist: mirrored analyzer/portal env files, Postgres data plane,
KB ingest, closed-ticket sync, and portal network rollout. Use after base install when
targeting cloud customer-default parity — not for core-only or single-profile custom rollouts.

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

## Guided deployment and result

Run the read-only preflight before approval to install. It checks the supported
host, Python, repository packages, config templates, model files, and required
offline inputs without printing secrets:

```bash
bash scripts/preflight_customer_deployment.sh \
  --repo-root /path/to/llm_notable_analysis \
  --model-path /opt/models/gemma-4-31B-it \
  --report-file /path/to/change-record/onprem-preflight.txt
```

For an air-gapped host, add:

```bash
  --offline \
  --portal-dist /path/to/staged/portal/dist \
  --wheelhouse /path/to/wheelhouse
```

After approval, follow the numbered steps below. At the end, save a deployment
result. The default audit is read-only; `--run-smoke` is optional because it
writes a synthetic file-drop input and needs separate operator approval.

```bash
sudo bash scripts/audit_customer_target_host.sh \
  --repo-root /path/to/llm_notable_analysis \
  --report-file /path/to/change-record/onprem-deployment-result.txt
```

The report contains check names, status, non-secret resource paths, and a final
count. `FAIL` blocks go-live. `UNKNOWN` identifies evidence the customer must
add, such as proof from a real SOAR or ServiceNow system.

## Who provides what

| Item | Product deployment provides | Customer provides or approves |
| --- | --- | --- |
| Application | Installer, systemd units, config templates, smoke and audit scripts | Approved release, host access, maintenance window |
| Host and GPU | Supported starting values and profile examples | RHEL-compatible host, GPU/driver, capacity approval |
| Models and packages | Pinned package/model names and offline staging guidance | Approved mirrors, wheelhouse, model files and licenses |
| Identity and network | Loopback service defaults and nginx example | DNS, TLS certificate, firewall rules, analyst accounts or SSO |
| Data | Schemas, ingest and retention tools | KB documents, SOAR feed, ServiceNow scope/token, data retention decision |
| Operations | Health checks, failure behavior, rollback steps | Backups, monitoring destination, change approval, incident ownership |

Do not put customer secrets, model files, production data, or deployment reports
in git.

## What retrieval does (accuracy)

Retrieve-then-inject: hybrid Postgres FTS + pgvector search, optional rerank, bounded
advisory snippets in the LLM prompt. Details:
[`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md).

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
8. **Smoke and result** — `scripts/smoke_service_chain.sh`,
   `scripts/smoke_postgres_rag.sh`, one notable → portal case, chat with KB +
   closed-ticket questions after sync, then `scripts/audit_customer_target_host.sh`
   with `--report-file`.

No additional application code changes are required when the above data plane
and env mirror are in place.

## Next

- Path B step 5: [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) — general and SPL KB ingest
- Path B step 6: [`../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md) — closed-ticket sync when ServiceNow is in scope
- Path B step 7: [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md) — TLS, nginx, analyst browser validation
- Path B step 9 / all paths: [`../../testing/TESTING.md`](../../testing/TESTING.md) — validation terminus
- Path order: root [`README.md`](../../../README.md#2-deploy--pick-one-path) section 2
