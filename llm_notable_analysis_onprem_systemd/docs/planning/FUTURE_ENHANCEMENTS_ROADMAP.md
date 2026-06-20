# Future Enhancements Roadmap

## Status

Planning backlog for capabilities **not yet shipped**. Items below marked
**Shipped** are implemented in code and covered by technical specs or operations
guides—listed here only for parity context, not as open backlog.

**Shipped analyzer enhancements** (SPL, Elasticsearch, Splunk investigation,
ServiceNow, query-result enrichment/interpretation):
[`../technical_specs/feature_enhancements_technical_spec.md`](../technical_specs/feature_enhancements_technical_spec.md)
and operations:
[`../operations/investigation/SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md),
[`../operations/investigation/ELASTICSEARCH_OPERATIONS.md`](../operations/investigation/ELASTICSEARCH_OPERATIONS.md),
[`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md),
[`../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md).

**Shipped analyst portal / case archive / chat** (on-prem and AWS):
[`../technical_specs/analyst_portal_case_archive_technical_spec.md`](../technical_specs/analyst_portal_case_archive_technical_spec.md),
[`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md),
[`../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../operations/analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md).

**AWS / on-prem parity** (Wave 1–3 runtime code-complete; real-AWS validation
operator-owned):
[`../../../s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../../s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md).

### Shipped vs backlog (codebase-verified)

| Area | On-prem | AWS (`s3_notable_pipeline`) |
| --- | --- | --- |
| Core file-drop analysis | Shipped | Shipped |
| Gzip notable intake | **Planned** | **Shipped** |
| Read-only Splunk investigation (`spl_readonly`) | Shipped | Shipped |
| Read-only Elasticsearch investigation (`elastic_readonly`) | Shipped | Shipped |
| Query-result enrichment (deterministic) | Shipped | Shipped |
| Query-result interpretation (optional LLM pass) | Shipped | Shipped |
| ServiceNow draft / approval-gated create | Shipped | Shipped |
| Analyst portal, case archive, Case Q&A | Shipped | Shipped |
| RAG / KB advisory context (`rag`) | Shipped | Shipped (Bedrock KB) |
| Threat-intel enrichment adapters | Backlog | Backlog |
| SOC SOAR playbook invocation (investigation-time) | Backlog | Backlog |
| LLM observability / Langfuse-class tracing | Backlog | Backlog |
| Asset / identity / CMDB context | Backlog | Backlog |
| AWS Security Lake / Athena read-only querying | N/A | Backlog |
| Gzip on-prem parity | Backlog | — |

Ops index: [`../operations/README.md`](../operations/README.md).

---

## Cross-cutting context roadmap (single source)

Backlog and adjacent capabilities that extend context around the notifier
workflow. Items here may be partially implemented, flagged off, or aspirational.
They are **not** runtime contracts until migrated into a technical spec after
review.

Roadmap grouping is capability-based; **[Deployment instantiation](#deployment-instantiation-on-prem-vs-aws)** maps the same bullets to hosting patterns.

### Threat intelligence enrichment adapters

**Status: backlog.**

Bring normalized vendor or internal enrichment **before** (or beside) the
structured LLM call, strictly separated from alert facts in prompts and payloads.

- Typical sources: VirusTotal, AbuseIPDB, GreyNoise, URLhaus, MISP, AlienVault OTX, commercial feeds, **internal TI** APIs.
- **On‑prem instantiation:** outbound HTTPS adapters on the analyzer host or a sidecar; host secrets stores for API keys; optional local cache (filesystem/redis) keyed by observable + TTL.
- **AWS instantiation:** outbound HTTPS from Lambda or VPC-attached task; Secrets Manager / SSM for secrets; DynamoDB or S3-backed TTL cache keyed by observable for quota and rerun stability.

Bounded behavior everywhere: timeouts, backoff, rate-limit handling, deterministic normalization into **`enrichment`**, structured **skipped | failed | rate_limited**, and observability correlation IDs **without logging secrets or bulk alert bodies**.

### VirusTotal adapter pattern (canonical)

**Status: backlog** (reference design for TI adapters above).

Governance-first: honor org rules on third-party telemetry; ship **explicit observables** only (IPs, hashes, domains, URLs policy allows)—never arbitrary full notable blobs unless approved.

**Placement:**

- Prefer after deterministic IOC extraction from the artifact (same placement on **on‑prem systemd** analyzer and **`s3_notable_pipeline` Lambda** workflows).
- **Default-off** behind config; optional Step Functions branch on AWS when orchestration separates enrichment from the primary Bedrock call.

**Behavior:**

| Concern | On‑prem | AWS |
|---------|---------|-----|
| API key | host secret store | Secrets Manager / SSM |
| Transport | thin HTTPS client (+ optional sidecar) | HTTPS from Lambda (or VPC egress path) |
| Resilience | timeouts, backoff, bounded concurrency optional | timeouts, backoff, bounded concurrency |
| Output shape | normalized small `enrichment` object | same |
| Prompt contract | direct alert facts vs enrichment clearly separated | same |

### Investigative querying

**Shipped concrete paths:**

- **Splunk:** bounded read-only SPL via Splunk MCP/REST (`splunk_investigation.py`), policies, deterministic row caps—see [`../operations/investigation/SPL_OPERATIONS.md`](../operations/investigation/SPL_OPERATIONS.md) and `query_result_enrichment.py`.
- **Elasticsearch:** bounded read-only Query DSL via `elasticsearch_investigation.py`, `elastic_query_generation.py`, and the `elastic_readonly` profile—see [`../operations/investigation/ELASTICSEARCH_OPERATIONS.md`](../operations/investigation/ELASTICSEARCH_OPERATIONS.md). Splunk and Elastic backends are **mutually exclusive** per deployment.

**Roadmap / parity intent:**

- Additional SIEM backends beyond Splunk and Elasticsearch remain **backlog** until a deliberate adapter design (not an abstract SIEM façade).
- **AWS-native read-only querying:** bounded SQL or parameterized queries over Security Lake / Athena over curated buckets; parity with Splunk/Elastic caps: scanned-byte limits, time windows, aggregates-first, deterministic merge—not raw dump into model context unless policy allows.

### Asset, identity, and ownership context

**Status: backlog.**

Enrich downstream reasoning with authoritative **advisory** context (never asserted as observable alert facts unless echoed from the notable).

- **On‑prem / enterprise:** CMDB, IdP/group membership, owner, workload criticality, business unit, VIP or admin tagging.
- **AWS:** AWS account Id, Organizations OU, resolver attributes (tags), environment/classification labels, workload owner/contact, assessed exposure posture where available (**Config**, **IAM Access Analyzer** signals, VPC exposure context as policy allows).

### Structured investigation planner (pattern)

**Status: backlog (design pattern).**

Separate **planned checks** from **allowed executions**: LLM may propose next checks; deterministic policy **allowlists** which integrations, queries, and budget classes may run—aligned with SOC workflow maturity targets (bounded tools, no open-ended autonomy).

### SOC-defined SOAR playbook invocation (roadmap)

**Goal:** During bounded investigation—not only at upstream ingest—invoke **Splunk SOAR playbooks authored and maintained by the SOC**, using a curated catalog rather than ad hoc playbook names invented by the model.

**Distinct from existing patterns:**

| Pattern | Role |
|---------|------|
| Phantom ingest templates (`soar_playbook/`, `s3_notable_pipeline/scripts/soar_playbook/`) | Upstream delivery: package a notable and drop to analyzer/S3 |
| `containment_playbook` in LLM JSON | Generated analyst guidance text; no SOAR API call |
| `LLM_STRUCTURED_OUTPUT_MODE=tool_call` | Local LLM JSON shaping for analysis/SPL fields; not SOAR execution |

**Proposed surface (open to refinement):** expose registered playbooks to the investigation planner as **LLM tool/function definitions**—one tool per allowlisted playbook or a single `invoke_soar_playbook` tool with an enum of SOC-registered IDs. The model may **propose** a run with structured inputs derived from alert context; **deterministic policy** decides whether that proposal is permitted, and a **thin SOAR adapter** performs the API call.

**Preferred architecture (planner + gate + adapter, not raw tool autonomy):**

1. **SOC catalog** — versioned registry (config or small data file) of playbook id/name, risk class (`read_only` | `writeback` | `action`), required inputs schema, and optional alert-class routing hints. Only catalog entries may be invoked.
2. **Proposal** — LLM tool call, deterministic router, or analyst UI selection produces a normalized `playbook_run_request` (playbook id, container/event refs, bounded parameter map).
3. **Policy gate** — allowlists by playbook id, risk class, time window, rate budget, and tenant scope; **fail closed** on unknown playbooks or out-of-policy parameters.
4. **Approval boundary** — `writeback` and `action` playbooks require explicit approval metadata in the payload (same semantics as ServiceNow create approval) unless a narrowly scoped auto-run profile is deliberately enabled.
5. **Adapter** — thin HTTPS client to Splunk SOAR REST (run playbook / add work item / pass inputs); normalize outcomes into `enrichment` or `recommended_actions` with run id, status, and errors—never merge adapter output into direct alert facts.
6. **Observability** — log playbook id, correlation id, policy decision, approval state, and terminal status; omit secrets and bulk container bodies.

**Alternative designs worth evaluating before implementation:**

- **Approval-first:** LLM or planner only *recommends* a playbook; analyst approves in payload or UI; adapter runs after approval (simplest operational posture).
- **Deterministic routing only:** no LLM playbook selection—code maps alert class / enrichment signals to catalog entries; LLM summarizes outcomes only.
- **Async handoff:** adapter enqueues a SOAR work item and returns immediately; poll or webhook for completion (better for long-running playbooks).

**Instantiation:**

| Concern | On‑prem | AWS |
|---------|---------|-----|
| Catalog storage | host config / versioned file under operator control | SSM Parameter Store, S3 config object, or DynamoDB catalog row |
| Credentials | host secret store for SOAR API token | Secrets Manager |
| Transport | analyzer host or sidecar egress to SOAR | Lambda/Step Functions branch with VPC egress if required |
| Orchestration hook | optional post-analysis step in service loop | optional Step Functions branch after primary Bedrock pass |
| Default | **off**; no playbook runs without explicit enable + catalog + policy | same |

**Status:** roadmap only—not in the bounded [feature enhancements scope](../technical_specs/feature_enhancements_technical_spec.md#2-scope) or locked technical spec until catalog schema, approval matrix, and adapter contract are reviewed.

### LLM observability and tracing (Langfuse-class, roadmap)

**Goal:** Give operators and engineers **visibility into multi-pass LLM work** (primary structured analysis, optional SPL/Elastic generation, optional query-result interpretation, repair attempts) without turning analyst markdown or Splunk comments into trace dumps.

**Problem today:** Application logs capture high-level outcomes (timeouts, policy skips, RAG degradation) but not a **first-class trace** across passes: which model ran, latency per call, token usage, repair vs success, grounding availability, or correlation back to `finding_id` / input file stem across a single notable processing run.

**Candidate platforms (evaluate one primary path; avoid dual shipping):**

| Option | Fit | Notes |
|--------|-----|-------|
| **[Langfuse](https://langfuse.com/)** (self-hosted or cloud) | Strong default for LLM-native traces, generations, scores, prompt/version tags | OpenTelemetry export supported; fits on-prem air-gap when self-hosted |
| **OpenTelemetry → existing backend** | Org already standardizes on OTEL | Instrument LiteLLM/vLLM/Bedrock clients; export to corporate collector, Grafana Tempo, Jaeger, Datadog, etc. |
| **Helicone / Arize Phoenix** | Comparable LLM gateways or eval UI | Same architectural boundaries as Langfuse; pick based on procurement and hosting |

**Distinct from existing patterns:**

| Pattern | Role |
|---------|------|
| Structured `logging` in `onprem_service` / Lambda | Operational events, errors, policy denies—retain as source of truth for SIEM |
| `metadata` on analysis JSON | Per-alert machine fields (`spl_query_rag_*`, sink status)—not a cross-alert trace UI |
| Markdown / HTML reports | Analyst deliverable—must stay free of raw trace payloads unless policy requires citations |

**Preferred architecture (thin instrumentation, default off):**

1. **Correlation** — one trace (or root span) per notable processing attempt, keyed by `finding_id` / input stem plus a service-generated `correlation_id` already used in logs.
2. **Spans** — child spans per LLM pass: `analyze_notable`, `spl_query_generation`, `elastic_query_generation`, `query_result_interpretation`, optional `repair`; tag `model_id`, `structured_output_mode`, pass outcome (`success` | `repair` | `timeout` | `policy_suppressed`).
3. **Redaction** — do **not** ship full prompts, API tokens, or unredacted notable bodies to the observability backend by default; use hashed or truncated previews and explicit operator opt-in for prompt capture in lab.
4. **Scores / feedback (optional)** — later tie analyst disposition or evaluation harness results to the same trace id for regression analysis.
5. **Adapter boundary** — a small `observability.py` (or OTEL wrapper) at the LLM transport edge—**not** scattered calls inside markdown or sink modules.

**Instantiation:**

| Concern | On‑prem | AWS |
|---------|---------|-----|
| Backend | self-hosted Langfuse or OTEL collector on corp network | Langfuse cloud, ADOT → X-Ray/CloudWatch, or approved SaaS |
| Credentials | host secret for Langfuse public/secret keys or OTEL headers | Secrets Manager / SSM |
| LiteLLM hook | optional Langfuse OTEL or callback on loopback proxy | same pattern on Bedrock path via SDK/OTEL |
| Default | **off** until `LLM_OBSERVABILITY_ENABLED` (or capability profile) + endpoint URL are set | same |
| Retention | operator-controlled; align with log/SIEM retention policy | account-level retention on chosen backend |

**Status:** roadmap only—not in [feature enhancements scope](../technical_specs/feature_enhancements_technical_spec.md#2-scope) until redaction rules, hosting choice, and correlation contract are reviewed. Complements **[Observability, audit posture, degraded mode](#observability-audit-posture-degraded-mode)** (application audit fields) rather than replacing it.

### Evidence layering and structured output taxonomy (aspirational alignment)

**Status: partial today; full taxonomy migration is backlog.**

Production analyzers currently use schemas such as `evidence_vs_inference`, competing hypotheses, and reconciliation objects. Target alignment for enrichment-heavy workflows emphasizes explicit lanes:

| Lane | Intended content |
|------|------------------|
| `direct_evidence` | verbatim or strict field-derived facts present in authoritative payload |
| `enrichment` | normalized adapter output (TI, CMDB query summary, deterministic query rollup) with source lineage |
| `inference` | model or analyst extrapolation |
| `unknowns` | explicit gaps |
| `recommended_actions` | bounded next steps |

Migrations evolve **validators and markdown** jointly; specs must not fracture without a versioning story.

### Approval-gated writeback and ticketing breadth

**Shipped:** ServiceNow Incident **draft + approval-gated create** (`servicenow.py`); see [`../operations/integrations/SERVICENOW_OPERATIONS.md`](../operations/integrations/SERVICENOW_OPERATIONS.md).

**Roadmap parity:** analogous patterns for **Jira**, generic **SOAR** tickets, Archer-style GRC payloads—thin adapters, deterministic drafts, mandatory approval metadata before consequential POSTs **by default**.

**AWS:** analogous **approval-gated** patterns for tagging, Security Hub suppression/finding edits, ticketing webhooks—the same approval boundary semantics; implementation lives in Lambda/Step Functions **only** behind explicit gates.

### RAG and runbooks (advisory context)

**Shipped** when `rag` profile is enabled. Operational SOPs, detection notes, SPL/Elastic field catalogs, escalation doctrine—retrieve as **SOC advisory** text. Never elevate retrieved wording to factual alert assertions without matching observable fields. Ops: [`../operations/rag/RAG_OPERATIONS.md`](../operations/rag/RAG_OPERATIONS.md), [`../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md).

### Analyst feedback loop and evaluation

**Status: backlog.**

Structured capture of disposition, corrections, TP/FP rationales for replay, retrieval, tuning metrics, regression evaluation—paired with deterministic batch replay (**batch harness** locally or **`s3_notable_pipeline`/Step Functions batches**).

### Deterministic preprocessing and risk cues

**Status: backlog.**

Prefer **severity or priority signals computed in code** (alert class, enrichment presence, anomaly scores, policy-hit counts) feeding the prompt as structured fields; LLM interprets—not invents—these aggregates.

### Detection and rule corpus context

**Status: backlog.**

Expose detection name/id, authored logic summary, ATT&CK links, historically known FPs/tuning narratives as advisory blocks when sources exist.

### Observability, audit posture, degraded mode

**Partial today** via structured logging and analysis `metadata`; expanded audit fields remain incremental.

Record model id, prompt versioning, policy denies, adapter outcomes, timings, approvals—omit secrets. Explicit operational states when Bedrock/runtime, Splunk, Elastic, RAG indexer, Athena, SNOW, TI, or SOAR are unavailable, capped, skipped, or policy-denied.

For **LLM-native trace visibility** (multi-pass spans, token/latency dashboards, eval linkage), see **[LLM observability and tracing (Langfuse-class, roadmap)](#llm-observability-and-tracing-langfuse-class-roadmap)**.

### Cost and quota envelopes

**Status: backlog** (policy envelopes exist piecemeal per adapter; unified envelope is not shipped).

Envelope Bedrock token spend, Athena bytes scanned, Splunk/Elastic concurrency, enrichment fan-out, Lambda duration/step retries—matching production guardrail defaults to policy.

### Quality and hallucination hygiene

**Partial today** via validators and prompt contracts; ongoing alignment with enrichment-heavy lanes is backlog.

Validated outputs cite only observable lanes: **direct_alert**, **adapter_enrichment**, **advisory_retrieval**, or explicit **unknown**. Third-party enrichment facts must reconcile to canonical API-derived fields.

### SPL / Elastic investigation and inference call layering

Mirrors consolidated guidance shared with **`s3_notable_pipeline`** parity narratives:

| Pass | Typical role | Status |
|------|----------------|--------|
| 1 | Full structured notable analysis | Shipped |
| 2 | Optional SPL or Elastic **field/query text** generation (`spl_readonly` / `elastic_readonly`) | Shipped |
| Execute | Bounded read-only search; deterministic compress/enrich (`query_result_enrichment.py`; **no mandatory LLM** on this rim) | Shipped |
| 3 | Optional bounded LLM interpretation of compressed query evidence (`query_result_interpretation.py`) | Shipped (off by default) |

Analyst portal, case archive, and chat are **shipped** on-prem and AWS. See the links in [Status](#status).

## Deployment instantiation (On-prem vs AWS)

Reference table for roadmap bullets above; **architecture truth** stays in prose sections—not duplicated in scattered repo-root lists.

| Cross-cutting roadmap area | Primary on‑prem pattern | Primary AWS (`s3_notable_pipeline` / Step Functions parity) pattern |
|---|---|---|
| Gzip notable intake | **Planned** — `*.json.gz` / `*.txt.gz` in `INCOMING_DIR`; `MAX_DECOMPRESSED_INPUT_BYTES` not in `config.env.example` yet — [on-prem file-drop ops](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) | **Shipped** — `incoming/*.gz` + optional S3 `ContentEncoding: gzip` — [AWS file-drop ops](../../../s3_notable_pipeline/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| TI adapters | Backlog — systemd host egress + cache dir | Backlog — Lambda egress + Dynamo/S3 TTL cache |
| Bounded investigation (Splunk) | **Shipped** — Splunk MCP/REST when `spl_readonly` enabled — [SPL ops](../operations/investigation/SPL_OPERATIONS.md) | **Shipped** — same modules in Lambda |
| Bounded investigation (Elasticsearch) | **Shipped** — Query DSL when `elastic_readonly` enabled — [Elastic ops](../operations/investigation/ELASTICSEARCH_OPERATIONS.md) | **Shipped** — same modules in Lambda |
| Bounded investigation (Athena / Security Lake) | N/A | **Backlog** |
| RAG / runbooks | **Shipped** — `RAG_*` paths + embeddings — [RAG ops](../operations/rag/RAG_OPERATIONS.md) | **Shipped** — Bedrock KB / retrieve |
| Read-only analyst portal | **Shipped** — Postgres + pgvector + notable-portal — [portal ops](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) | **Shipped** — DynamoDB + S3 + portal Lambda |
| Orchestration | single service loop (+ optional playbook backlog) | EventBridge → Lambda; optional Step Functions for fan-out retries |
| Writeback approvals | **Shipped** — SNOW payload approvals — [ServiceNow ops](../operations/integrations/SERVICENOW_OPERATIONS.md) | **Shipped** — same semantics + IAM-scoped gated AWS actions |
| SOC SOAR playbook runs | Backlog — catalog + policy gate + thin SOAR adapter on analyzer host | Backlog — catalog in SSM/S3/Dynamo + gated Lambda/Step Functions branch |
| LLM tracing / Langfuse-class | Backlog — OTEL or Langfuse at LLM transport edge; self-hosted or corp collector | Backlog — Langfuse cloud, ADOT, or approved OTEL backend |
| Replay / caching | partial — scripted batch + disk artifacts | partial — DynamoDB/S3 envelopes + versioning |

---
