# Knowledge Base Operations

This runbook explains how operators add, validate, rebuild, and roll back
knowledge-base content for optional RAG grounding.

## What This Controls

This guide controls the **content lifecycle** for the knowledge base: source
documents, rebuilds, ingest reports, rollback, and content quality. Retrieval
settings such as context budgets, embedding model, backend, and fail-closed
behavior are covered in [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md).

There are three supported KB content lanes for investigation queries:

- **General SOC KB**: normal advisory context rendered as
  `SOC_OPERATIONAL_CONTEXT` when the `rag` profile is selected.
- **SPL query KB**: Splunk-specific facts rendered as
  `SPL_QUERY_GROUNDING_CONTEXT` when `SPL_QUERY_RAG_ENABLED=true`.
- **Elasticsearch query KB**: Elastic-specific facts rendered as
  `ELASTICSEARCH_GROUNDING_CONTEXT` when `ELASTICSEARCH_GROUNDING_ENABLED=true`.

Splunk and Elastic grounding KBs are separate from each other and from the
general SOC KB. See
[`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) and
[`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md) for backend-specific
onboarding checklists.

## Recommended Starting Posture

- Keep source documents short, reviewed, and clearly headed.
- Store authoritative source documents in an operator-controlled location, not
  only on the runtime host.
- Rebuild manually after approved content changes.
- Validate ingest reports before adding the `rag` profile.
- Do not store secrets, tokens, raw auth headers, or private keys in KB docs.

## Customer Decisions

- Who owns KB source content and review cadence?
- Which SOPs, Splunk references, escalation notes, and runbooks are approved for
  model advisory context?
- How are stale documents retired before rebuild?
- How are bad KB updates rolled back and audited?
- Which environments may use customer production examples in KB material?

## Investigation Query Grounding — What To Collect Per Customer

Use this before enabling **SPL query RAG** or **Elasticsearch grounding**. You
do **not** need a complete field encyclopedia for every index. You **do** need
approved environment facts and a few representative alerts.

### Splunk (`SPL_QUERY_RAG_ENABLED`)

**Must have from Splunk owners:**

- Approved `index=` and `sourcetype=` names for investigation hunts
- Approved macro and datamodel names (if used in generated SPL)
- Whether query **execution** is in scope; if yes, align KB indexes with
  `SPLUNK_SEARCH_ALLOWED_INDEXES` and command policy
- 3–5 representative notables per major log source for spot-checks
- Rollout choice: generation-only vs execute; `suppress` vs
  `fallback_to_ungrounded`

**Nice to have in SPL query KB (not validated as an allowlist in code):**

- Common field names per sourcetype (`Account_Name`, `src_ip`, etc.)
- Approved example SPL patterns

**Comes from the alert automatically:**

- Observable field values in `SECURITY ALERT INPUT` (user, host, IP, etc.)

**Not required upfront for engineering work:**

- Full schema export of every index

Detailed checklist: [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) section
**Customer Onboarding — Splunk Query Grounding**.

### Elasticsearch (`ELASTICSEARCH_GROUNDING_ENABLED`)

**Must have from Elastic owners:**

- `ELASTICSEARCH_INDEX_ALLOWLIST` (concrete index names or approved patterns)
- `ELASTICSEARCH_ALLOWED_FIELDS` (ECS and/or custom dotted fields used in hunts)
- `ELASTICSEARCH_TIMESTAMP_FIELD` (usually `@timestamp`)
- Read-only API key scoped to approved indexes
- Index/field mapping notes and approved Query DSL examples for the Elastic query KB
- 3–5 representative notables per major data source for spot-checks
- Rollout choice: generation-only vs execute; `suppress` vs
  `fallback_to_ungrounded`

Unlike Splunk, **field names are enforced** in config and validators — operators
must set `ELASTICSEARCH_ALLOWED_FIELDS` explicitly; grounding KB supplements but
does not replace that list.

Detailed checklist: [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md)
section **Customer Onboarding — Elasticsearch Query Grounding**.

### Ops vs engineering

| Work | Owner |
|------|-------|
| Curate source docs, ingest, enable flags, spot-check alerts | Operators / platform owners |
| Prompt labeling, retrieval query shaping, eval harness | Engineering (see [`PROMPT_ENHANCEMENTS_PLAN.md`](../planning/PROMPT_ENHANCEMENTS_PLAN.md)) |

## Runtime Contract

The current production-oriented backend is PostgreSQL FTS + pgvector:

- Source documents: `/opt/llm-notable-analysis/knowledge_base/source_docs`
- Ingest artifacts: `/opt/llm-notable-analysis/knowledge_base/index`
- Runtime table: `RAG_POSTGRES_SCHEMA`.`RAG_POSTGRES_CHUNKS_TABLE`
- SPL source documents:
  `/opt/llm-notable-analysis/knowledge_base/spl_query_source_docs`
- SPL ingest artifacts:
  `/opt/llm-notable-analysis/knowledge_base/spl_query_index`
- SPL runtime table:
  `RAG_POSTGRES_SCHEMA`.`SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE`
- Elastic source documents:
  `/opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs`
- Elastic ingest artifacts:
  `/opt/llm-notable-analysis/knowledge_base/elasticsearch_index`
- Elastic runtime table:
  `RAG_POSTGRES_SCHEMA`.`ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE`
- Config source: `/etc/notable-analyzer/config.env`
- Setup helper: `scripts/setup_postgres_rag.sh`

SQLite/FAISS remains a fallback backend for smaller or disconnected testing
flows, but new on-prem deployments default to `RAG_BACKEND=postgres`.

## Add Or Update Documents

1. Stage approved `.txt` or `.docx` files under:

   ```bash
   /opt/llm-notable-analysis/knowledge_base/source_docs
   ```

2. Use clear filenames and headings. Good examples:

   ```text
   windows_powershell_triage_sop.txt
   vpn_impossible_travel_runbook.docx
   splunk_index_field_reference.txt
   ```

3. Rebuild the configured Postgres RAG table:

   ```bash
   sudo bash scripts/setup_postgres_rag.sh \
     --config-env /etc/notable-analyzer/config.env \
     --source-dir /opt/llm-notable-analysis/knowledge_base/source_docs \
     --index-dir /opt/llm-notable-analysis/knowledge_base/index
   ```

4. Review the ingest report:

   ```bash
   sudo ls -l /opt/llm-notable-analysis/knowledge_base/index
   sudo less /opt/llm-notable-analysis/knowledge_base/index/ingest_report.json
   ```

5. For release validation, run the Docker-backed pgvector smoke when Docker is
   available:

   ```bash
   bash scripts/smoke_postgres_rag.sh
   ```

6. Run the service-chain smoke test after services are started:

   ```bash
   sudo bash scripts/smoke_service_chain.sh \
     --config-env /etc/notable-analyzer/config.env
   ```

## Add Or Update SPL Query KB Documents

Use the SPL query KB for customer-specific Splunk environment facts that should
ground generated SPL:

- index names
- sourcetypes
- field dictionaries
- macro names
- saved searches
- CIM/datamodel notes
- approved query examples

1. Stage approved `.txt` or `.docx` files under:

   ```bash
   /opt/llm-notable-analysis/knowledge_base/spl_query_source_docs
   ```

2. Rebuild the SPL query table:

   ```bash
   sudo bash scripts/setup_postgres_rag.sh \
     --config-env /etc/notable-analyzer/config.env \
     --spl-query-rag
   ```

3. Review:

   ```bash
   sudo less /opt/llm-notable-analysis/knowledge_base/spl_query_index/ingest_report.json
   ```

4. Enable only after review:

   ```bash
   CAPABILITY_PROFILES=core,spl_readonly
   SPL_QUERY_RAG_ENABLED=true
   ```

Generated SPL may use an index, sourcetype, macro, or datamodel only when it is
present in the alert itself or in `SPL_QUERY_GROUNDING_CONTEXT`. When SPL KB
material is used, the output includes `primary_spl_query_grounding_refs` with
`source_file` and `section_path`.

## SPL Query KB Document Template

Use one short document per log source or hunt pattern. Keep each section
atomic so retrieval can return just the index/field block without unrelated
prose.

Example filename: `wineventlog_authentication_reference.txt`

```text
# Windows Authentication — Splunk Environment Reference
Owner: SOC Platform / Splunk Admin
Reviewed: 2026-03-01
Source: Approved Splunk deployment inventory

## Indexes
- index=wineventlog — primary Windows Security and System events
- index=wineventlog_sec — restricted Security-only copy (use when RBAC requires)

## Sourcetypes
- sourcetype=WinEventLog:Security — logon, logoff, privilege use (event IDs 4624, 4625, 4672)
- sourcetype=WinEventLog:System — service and driver events

## Key fields
- Account_Name — target user
- src_ip — source IP for remote logons
- ComputerName — endpoint
- EventCode — Windows event ID

## Approved macros
- `macro-auth-failures(1)` — failed logons for user `$user$` in last 24h

## Example query (approved pattern)
index=wineventlog sourcetype=WinEventLog:Security EventCode=4625
| stats count by Account_Name, src_ip
| sort - count

## Notes
- Do not use index=main for authentication hunts in production.
- CIM Authentication datamodel is normalized on wineventlog only.
```

Headings become chunk boundaries at ingest time. Prefer explicit token lines
(`index=...`, `sourcetype=...`, macro names) over narrative paragraphs.

## SPL Query KB — Good Vs Bad Content

| Good | Bad |
|------|-----|
| Explicit `index=`, `sourcetype=`, field, and macro names | Vague prose such as "check the auth index" with no token |
| One log source or hunt pattern per section | Mixed firewall, VPN, and auth facts in one undifferentiated doc |
| Approved example SPL with real tokens from your deployment | Copy-pasted generic Splunk tutorials with fake index names |
| Owner, review date, and source system in the header | Stale inventory with no retirement path |
| Field dictionaries tied to a sourcetype | Entire CIM PDFs with no local mapping |
| Short, retrieval-friendly sections | 40-page runbooks that dilute vector search |

Keep broad triage SOPs in the **general SOC KB** (`source_docs`). Put only
Splunk tokens that should **authorize** generated SPL in the **SPL query KB**.

## SPL Query KB — Quality Checklist After Ingest

Run this after rebuild and before enabling `SPL_QUERY_RAG_ENABLED=true`:

1. **Ingest report** — `spl_query_index/ingest_report.json` shows expected
   document and chunk counts; no unexpected zero-chunk files.
2. **Token coverage** — for each approved production index/sourcetype you expect
   in hunts, confirm a dedicated chunk exists with the literal token
   (`index=wineventlog`, not paraphrased).
3. **Retrieval spot-check** — process one representative notable per major log
   source (auth, endpoint, network, email). In analysis metadata or logs,
   confirm `SPL_QUERY_GROUNDING_CONTEXT` (or grounding refs) cites the expected
   source file/section, not an unrelated doc.
4. **Generated SPL** — with `SPL_QUERY_GENERATION_ENABLED=true` and execution
   still off, review `primary_spl_query` strings: they should use grounded
   tokens when the alert type matches KB content, and should not invent indexes
   outside alert + grounding.
5. **Failure mode** — first rollout uses `SPL_QUERY_RAG_FAILURE_MODE=suppress`
   so weak or missing retrieval omits SPL rather than emitting ungrounded tokens.

Record who ran the checklist and the date. Re-run when source docs or embedding
settings change.

## SPL Query KB — Retrieval Tuning (Operators)

Retrieval is the step **between** curated docs in Postgres and the
`SPL_QUERY_GROUNDING_CONTEXT` block in the SPL-generation prompt. It does not
change prompt text or validator rules; it controls **which KB snippets** are
selected for each alert.

**What the service searches with today:** alert text plus the six competing
hypotheses (see `build_spl_query_grounding_query` in `spl_query_grounding.py`).
Postgres lexical + vector search returns candidates; optional reranking and
deduplication apply; the top snippets are rendered up to configured limits.

**SPL-specific knobs** (in `config.env`):

| Setting | Default | Operator use |
|---------|---------|--------------|
| `SPL_QUERY_RAG_MAX_SNIPPETS` | `4` | Lower if prompts feel noisy; raise only when spot-checks show missing index/field chunks |
| `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS` | `1600` | Total character cap for all SPL grounding snippets combined |
| `SPL_QUERY_RAG_FAILURE_MODE` | `suppress` | `suppress` omits SPL when grounding fails; `fallback_to_ungrounded` allows alert-only SPL |

**Shared retrieval knobs** (same Postgres path as general RAG; see
[`RAG_OPERATIONS.md`](RAG_OPERATIONS.md)):

- `RAG_RERANK_ENABLED` — enable after staging the reranker model; often improves
  snippet relevance when many similar chunks exist.
- `RAG_LEXICAL_TOP_K`, `RAG_VECTOR_TOP_K`, `RAG_CANDIDATE_POOL_LIMIT`,
  `RAG_FUSED_RANK_LIMIT_*`, `RAG_NEAR_DUPLICATE_SIMILARITY_THRESHOLD` — widen
  only when spot-checks show the right doc never surfaces.

**Tuning workflow:**

1. Fix KB content first (template and good/bad rules above).
2. Run the quality checklist on default snippet/budget settings.
3. If grounding is consistently irrelevant, split or rewrite docs before raising
   snippet counts.
4. If the right doc exists but never appears in grounding, try rerank or modest
   pool increases one knob at a time; re-run spot-checks after each change.

**Engineering follow-ups** (prompt labeling, retrieval query shaping, eval
harness) are tracked in
[`PROMPT_ENHANCEMENTS_PLAN.md`](../planning/PROMPT_ENHANCEMENTS_PLAN.md) under
**Deferred — SPL query RAG**; those are code/prompt changes, not operator KB
curation.

## Add Or Update Elasticsearch Query KB Documents

Use the Elasticsearch query KB for customer-specific index patterns, field
mappings, and approved Query DSL patterns that should ground generated hunts:

- index names and approved index patterns
- ECS and custom field dictionaries
- timestamp field conventions
- approved bool/filter Query DSL examples
- notes mapping alert types to indexes

1. Stage approved `.txt` or `.docx` files under:

   ```bash
   /opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs
   ```

2. Rebuild the Elasticsearch query table with corpus ingest (use the Elastic
   table name from config):

   ```bash
   sudo /opt/notable-analyzer/venv/bin/python \
     -m onprem_rag_notable_analysis.future.corpus_ingest \
     --config-env /etc/notable-analyzer/config.env \
     --backend postgres \
     --source-dir /opt/llm-notable-analysis/knowledge_base/elasticsearch_source_docs \
     --index-dir /opt/llm-notable-analysis/knowledge_base/elasticsearch_index \
     --postgres-chunks-table elasticsearch_query_chunks
   ```

   Replace `elasticsearch_query_chunks` with
   `ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE` when customized. Run
   `scripts/setup_postgres_rag.sh` once without `--skip-db-setup` if the Postgres
   schema or pgvector extension is not yet provisioned.

3. Review ingest artifacts under `elasticsearch_index/ingest_report.json`.

4. Set config allowlists **before** enabling grounding:

   ```bash
   ELASTICSEARCH_INDEX_ALLOWLIST=logs-auth,security-endpoint
   ELASTICSEARCH_ALLOWED_FIELDS=@timestamp,user.name,host.name,source.ip,event.action
   ELASTICSEARCH_TIMESTAMP_FIELD=@timestamp
   ```

5. Enable only after review:

   ```bash
   CAPABILITY_PROFILES=core,elastic_readonly
   INVESTIGATION_QUERY_BACKEND=elasticsearch
   ELASTICSEARCH_GROUNDING_ENABLED=true
   ```

Generated Query DSL may use an index pattern or field only when it appears in
the alert, `ELASTICSEARCH_GROUNDING_CONTEXT`, or the configured allowlists
(execution also projects `_source` to `ELASTICSEARCH_ALLOWED_FIELDS`).

## Elasticsearch Query KB Document Template

Example filename: `logs_auth_ecs_reference.txt`

```text
# Authentication Logs — Elasticsearch Environment Reference
Owner: SOC Platform / Elastic Admin
Reviewed: 2026-03-01
Source: Approved Elastic deployment inventory

## Index patterns
- logs-auth — interactive and VPN authentication events
- security-endpoint-* — endpoint telemetry (use only when alert sourcetype maps here)

## Timestamp field
- @timestamp — required range bound for all hunts

## ECS fields (approved)
- user.name — principal username
- host.name — endpoint hostname
- source.ip — client source address
- event.action — normalized action (logon, logon-failed, etc.)
- event.category — authentication, process, network

## Custom fields (if not ECS-normalized)
- winlog.event_id — Windows event ID when present on logs-auth

## Example Query DSL (approved pattern)
index_pattern: logs-auth
bool.filter: range @timestamp last 24h, term user.name, term event.action

## Notes
- Do not use logs-* wildcard in production hunts unless explicitly approved.
```

Keep index patterns and field names as literal tokens retrieval can match.

## Elasticsearch Query KB — Good Vs Bad Content

| Good | Bad |
|------|-----|
| Literal index pattern names matching `ELASTICSEARCH_INDEX_ALLOWLIST` | Generic Elastic tutorial with fake index names |
| Field list aligned with `ELASTICSEARCH_ALLOWED_FIELDS` | Fields documented only in KB but missing from config allowlist |
| One data domain per section (auth, endpoint, network) | Mixed mappings with no alert-type guidance |
| Approved bool/filter examples | Aggregations, scripts, or query_string examples |
| Timestamp field called out explicitly | Assumed `@timestamp` with no doc entry |

## Elasticsearch Query KB — Quality Checklist After Ingest

1. **Ingest report** — expected document and chunk counts.
2. **Allowlist alignment** — every index pattern in KB docs appears in
   `ELASTICSEARCH_INDEX_ALLOWLIST`; every documented hunt field appears in
   `ELASTICSEARCH_ALLOWED_FIELDS`.
3. **Retrieval spot-check** — one representative notable per major index;
   confirm grounding cites the expected source file/section.
4. **Generated Query DSL** — review draft queries with Elastic owners; no
   invented index patterns or fields outside alert + grounding + allowlists.
5. **Failure mode** — first rollout uses `ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress`.

## Elasticsearch Query KB — Retrieval Tuning (Operators)

Same retrieval pipeline as SPL grounding (Postgres FTS + pgvector). Elastic-specific
knobs:

| Setting | Default | Operator use |
|---------|---------|--------------|
| `ELASTICSEARCH_GROUNDING_MAX_SNIPPETS` | `4` | Lower if noisy; raise only when spot-checks miss index/field chunks |
| `ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS` | `1600` | Combined snippet character cap |
| `ELASTICSEARCH_GROUNDING_FAILURE_MODE` | `suppress` | Omit generated queries when grounding unavailable |

Shared retrieval knobs: [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md). Tuning
workflow matches the SPL section above (fix content first, then spot-check, then
adjust snippets/rerank).

## Content Best Practices

- Treat KB content as advisory context, not current-alert evidence.
- Do not store secrets, API tokens, raw auth headers, private keys, or customer
  production payloads in KB source docs unless the deployment owner explicitly
  approves that data handling model.
- Prefer short SOPs, runbooks, index/field references, and escalation guidance
  over large mixed-purpose documents.
- Keep SPL token catalogs in the SPL query KB when those tokens should authorize
  generated queries; keep broad triage prose in the general SOC KB.
- Use headings and sections that describe the operational task, such as
  `PowerShell EncodedCommand Triage` or `VPN Impossible Travel Escalation`.
- Keep source facts separate from recommendations. If a document is opinion or
  local policy, label it that way.
- Remove stale or superseded docs before rebuilding, or move them to an
  operator-controlled archive outside `source_docs`.
- Record content owner, review date, and source system when possible.

## Rebuild Cadence

Run a rebuild when:

- source documents are added, changed, or removed
- `RAG_EMBEDDING_MODEL`, `RAG_VECTOR_DIMENSIONS`, or reranker settings change
- a schema/table name changes in `config.env`
- `SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE` or SPL query source docs change
- `ELASTICSEARCH_GROUNDING_POSTGRES_CHUNKS_TABLE` or Elastic query source docs change
- operators need to roll back a bad KB content update

There is no scheduled KB rebuild unit in the current package. Rebuilds are an
operator action through `scripts/setup_postgres_rag.sh`.

## Rollback

The ingest command writes `chunks.jsonl` and `ingest_report.json` for
traceability, but the PostgreSQL table is replaced during rebuild. To roll back
bad KB content:

1. Remove or replace the bad source document under `source_docs`.
2. Restore the prior approved document set from the operator's source-control or
   file-backup process.
3. Rerun `scripts/setup_postgres_rag.sh`.
4. Run `scripts/smoke_service_chain.sh`.

Keep the authoritative source documents in a controlled location outside the
runtime host if rollback auditability is required.

## Validation Checklist

- `CAPABILITY_PROFILES` includes `rag` only when operators intend to use
  retrieved context.
- `RAG_BACKEND=postgres` for the Postgres/pgvector path.
- `RAG_POSTGRES_DSN` points to the intended local database.
- `RAG_VECTOR_DIMENSIONS=768` for `BAAI/bge-base-en-v1.5`.
- `RAG_RERANK_ENABLED=true` only after the reranker model is staged and tested.
- `SPL_QUERY_RAG_ENABLED=true` only after the SPL source docs have been ingested
  into `SPL_QUERY_RAG_POSTGRES_CHUNKS_TABLE`; SPL generation itself should come
  from the `spl_readonly` profile.
- `SPL_QUERY_RAG_FAILURE_MODE=suppress` for the first rollout unless operators
  explicitly accept ungrounded fallback.
- `ELASTICSEARCH_GROUNDING_ENABLED=true` only after Elastic source docs are
  ingested, allowlists are set, and the quality checklist passes.
- `ELASTICSEARCH_GROUNDING_FAILURE_MODE=suppress` for the first Elastic grounding rollout.
- `ingest_report.json` shows the expected document and chunk counts.
- `scripts/smoke_postgres_rag.sh` passes on a Docker-capable validation host.
- The service-chain smoke test produces a report.

## Related Docs

- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md) — shared retrieval tuning
- [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) — Splunk generation, execution, onboarding
- [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md) — Elastic generation, execution, onboarding
- [`PROMPT_ENHANCEMENTS_PLAN.md`](../planning/PROMPT_ENHANCEMENTS_PLAN.md) — engineering prompt/RAG follow-ups
