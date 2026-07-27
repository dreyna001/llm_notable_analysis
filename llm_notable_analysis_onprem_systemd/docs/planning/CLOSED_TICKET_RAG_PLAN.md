# Closed Ticket RAG Plan

## Goal

Use customer-local closed ServiceNow and Archer tickets as historical context for
initial alert analysis and the analyst chatbot, primarily to reduce repeated
false-positive investigation.

## Locked Decisions

- Default closed-ticket retention window: **30 days** (`CLOSED_TICKET_RETENTION_DAYS`;
  allowed values 30, 60, 90).
- Each deployment and its data remain inside one customer environment.
- Pull from ticketing systems; optionally add push later as an accelerator.
- Store the complete source payload unchanged.
- Do not require redaction, canonical schema mapping, or customer-specific ETL.
- Add source-provided labels/display values when available; never depend on them.
- Use deterministic code for sync, identity, updates, deduplication, rendering,
  indexing, and citations.
- Use LLMs for semantic comparison and interpretation, not synchronization state.
- Historical tickets are advisory context, not evidence about the current alert.

## Workflow

1. Configure endpoint, read-only credential, and saved query/report for closed
   security tickets.
2. Backfill, then incrementally pull new and changed tickets using source IDs and
   update cursors; periodically reconcile.
3. Store the raw payload, source ID/URL, timestamps, content hash, and sync state.
4. Render all available fields into searchable text; chunk oversized tickets.
5. Build a hybrid keyword and vector index over rendered content.
6. At alert time, create multiple searches from the detection, entities,
   behavior, and possible false-positive conditions.
7. Merge and rerank candidates; return recent and diverse benign and malicious
   precedents with source excerpts and citations.
8. Supply ticket context to the first-analysis agent in a separate advisory lane.
9. Use the same corpus for chatbot retrieval with a separate retrieval budget.
10. Sync later ticket closures so analyst outcomes become future context.

## Assumptions and Constraints

- The ticket API or approved export is reachable and supports pagination.
- A stable source ID is available; an update cursor is preferred, with content
  hashing and reconciliation as fallback.
- The customer can define the closed-security-ticket scope with a saved query,
  report, table, or application.
- Opaque codes without explanatory text or metadata cannot be interpreted
  reliably by either RAG or an LLM.
- Retrieval is fail-soft and bounded by record, chunk, latency, and token limits.
- Ticket quality, stale dispositions, rule drift, and retrieval misses remain
  possible; the agent must compare matching and differing conditions.
- RAG alone must not automatically close alerts.

## Implementation Slices

### On-prem (implemented in `llm_notable_analysis_onprem_systemd`)

1. ServiceNow closed-ticket raw sync, Postgres store, attachment download, bounded
   post-sync indexing (`index_pending_closed_tickets`).
2. Deterministic render/chunk, hybrid retrieval, first-pass advisory lane.
3. Analyst portal chat closed-ticket lane (with portal env flags and DB grants).
4. Operator runbook: `docs/operations/integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md`.

### Not in on-prem scope yet

1. Define the raw ticket envelope and Archer connector interface.
2. Add closed-ticket retrieval citations in product UI (advisory lane is prompt-only).
3. Archer pull adapter against the same raw envelope.
4. Sync health dashboards, retrieval metrics, replay evaluation.

## Implementation Execution

- Use **Composer 2.5 subagents** for implementation.
- Split parallel subagents by connector/sync, indexing/retrieval, alert-agent
  integration, chatbot integration, and tests/docs.
- Keep one coordinating agent responsible for shared contracts, parity across
  on-prem/AWS/Azure, integration, and final verification.

## Acceptance Criteria

- One-time customer setup is limited to endpoint, credential, and closed-ticket
  scope.
- Backfill and incremental updates require no schema-mapping exercise.
- Hybrid search returns cited raw-ticket excerpts for alert and chatbot queries.
- Ticket-system or index failure does not block baseline alert analysis.
- Evaluation demonstrates improved historical-ticket retrieval without treating
  precedent as current-alert evidence.
