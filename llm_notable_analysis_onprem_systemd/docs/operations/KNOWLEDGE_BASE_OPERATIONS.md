# Knowledge Base Operations

This runbook explains how operators add, validate, rebuild, and roll back
knowledge-base content for optional RAG grounding.

## What This Controls

This guide controls the **content lifecycle** for the knowledge base: source
documents, rebuilds, ingest reports, rollback, and content quality. Retrieval
settings such as context budgets, embedding model, backend, and fail-closed
behavior are covered in [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md).

There are now two supported KB content lanes:

- **General SOC KB**: normal advisory context rendered as
  `SOC_OPERATIONAL_CONTEXT` when the `rag` profile is selected.
- **SPL query KB**: Splunk-specific facts rendered as
  `SPL_QUERY_GROUNDING_CONTEXT` when `SPL_QUERY_RAG_ENABLED=true`.

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
- `ingest_report.json` shows the expected document and chunk counts.
- `scripts/smoke_postgres_rag.sh` passes on a Docker-capable validation host.
- The service-chain smoke test produces a report.
