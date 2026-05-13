# Executive On-Prem Workflow Overview

## Purpose

This document explains the on-premises notable-analysis workflow end to end for executive and program stakeholders. It covers the file-drop operating model, local LLM inference through LiteLLM routing to vLLM, optional RAG grounding, optional SPL generation and read-only execution, optional Splunk writeback, and optional ServiceNow incident draft/create behavior.

The workflow is designed for a customer-controlled environment where notable data can remain on premises or in an air-gapped enclave. The default model configuration is `gemma-4-31B-it`, and the same service can be pointed at a GPT-OSS model when it is served through a compatible local OpenAI-style endpoint.

## Executive Summary

The on-prem workflow provides a bounded local analysis path for security notables:

1. SOAR, SFTP, NFS, or an operator drops one `.json` or `.txt` notable into the incoming directory.
2. A `systemd` service polls the directory and processes eligible files in FIFO order.
3. The service normalizes the notable as JSON or text and sends it to a local LiteLLM endpoint.
4. The local model produces structured alert analysis, including verdict, evidence, hypotheses, IOCs, and ATT&CK mappings.
5. The service parses, repairs when possible, validates, and filters the model output.
6. Optional RAG injects SOC operating context from local SOPs, data dictionaries, Splunk index references, and related knowledge-base documents.
7. Optional SPL generation adds one investigation query per hypothesis.
8. Optional read-only Splunk query execution validates and runs bounded investigation searches, then summarizes results in the report.
9. Optional ServiceNow logic builds incident drafts and can create incidents only when enabled and approved.
10. The service writes a markdown report, moves successful input files to processed storage, and quarantines failed inputs.

The design keeps the LLM focused on synthesis and explanation. File movement, validation, ATT&CK filtering, query policy, writeback, approval checks, retention, and service operation remain deterministic.

## Business Outcome

The workflow gives analysts an on-prem first-pass investigation package without sending notable content to a cloud LLM. It can produce:

- A direct alert reconciliation verdict with confidence.
- Evidence separated from inference.
- Six competing benign/adversary hypotheses with recommended pivots.
- Extracted indicators of compromise.
- Validated MITRE ATT&CK techniques and confidence scores.
- Optional SPL queries tied to specific hypotheses.
- Optional query result summaries from read-only Splunk execution.
- Optional ServiceNow incident draft or approved incident creation result.

The system supports analyst decision-making. It is not intended to autonomously close, suppress, escalate, or contain alerts.

## End-to-End Workflow

### 1. Notable Intake

The analyzer runs in `file_drop` mode. It watches `INCOMING_DIR`, which defaults to:

```text
/var/notables/incoming
```

The preferred integration pattern is SOAR-to-analyzer file delivery over SFTP. SOAR packages one notable plus supporting context into a JSON payload and writes it to the incoming directory. Text input is also supported for simpler integrations or fallback workflows.

The service processes only `.json` and `.txt` files and does not recurse into subdirectories. This keeps the intake contract simple and predictable.

### 2. Local Service Loop

The `notable-analyzer` `systemd` service loads `/etc/notable-analyzer/config.env`, ensures the required directories exist, initializes the ATT&CK validator, initializes the local LLM client, and then polls for incoming files.

The default processing mode is sequential. Optional bounded concurrency can be enabled with `CONCURRENCY_ENABLED`, `MAX_WORKERS`, and `MAX_QUEUE_DEPTH` when the host has enough CPU/GPU headroom.

### 3. Local Inference Runtime

The inference layer is a local OpenAI-compatible endpoint, normally served by LiteLLM on loopback and routed to vLLM:

```text
http://127.0.0.1:4000/v1/chat/completions
```

The default systemd unit serves:

```text
gemma-4-31B-it
```

GPT-OSS can be used when the local inference server exposes the same OpenAI-compatible chat-completions contract. Operators must keep these values aligned:

- vLLM model path.
- LiteLLM model alias and vLLM served model name.
- `LLM_MODEL_NAME` in `/etc/notable-analyzer/config.env`.
- Tool-call parser or chat template settings when `LLM_STRUCTURED_OUTPUT_MODE=tool_call`.

For Gemma, the current package defaults to prompt-JSON mode. For GPT-OSS or Gemma tool-call mode, vLLM must be launched with compatible parser/template settings. If tool-call parsing fails for a request, the service falls back to prompt-JSON behavior for that request.

### 4. Structured LLM Analysis

The service sends the notable to the local model with a bounded cybersecurity analysis prompt. The prompt requires the model to:

- Use only direct alert facts for current-case evidence.
- Separate evidence from inference.
- Return a structured output contract.
- Generate exactly six competing hypotheses.
- Use MITRE ATT&CK v17 technique IDs.
- State uncertainty instead of inventing missing context.
- Leave unknown facts as `unknown`.

The base output contract includes alert reconciliation, competing hypotheses, evidence versus inference, IOC extraction, and TTP analysis.

### 5. RAG Grounding

When `RAG_ENABLED=true`, the service attempts to initialize a local RAG provider. The default production-oriented backend is PostgreSQL with PostgreSQL FTS, pgvector, BGE embeddings, and optional BGE reranking. SQLite FTS5 + FAISS remains available as a local fallback for smaller or lab deployments. The knowledge base can include SOPs, index and sourcetype references, field mapping notes, investigation playbooks, query examples, and local operating guidance.

RAG context is rendered into a `SOC_OPERATIONAL_CONTEXT` block. It is advisory context only. The workflow explicitly prevents retrieved guidance from being treated as current-alert evidence unless the same fact appears in the notable itself.

If RAG initialization or retrieval fails, the analyzer continues without RAG rather than stopping the service.

### 6. SPL Query Generation

When `SPL_QUERY_GENERATION_ENABLED=true`, the service performs a second bounded LLM call after the base analysis. This second call is dedicated to generating SPL query fields for the six hypotheses.

Each generated query must be tied to a hypothesis and include:

- Query strategy.
- Primary SPL query.
- Rationale for the query.
- Result pattern that would support the hypothesis.
- Result pattern that would weaken the hypothesis.

The SPL-generation prompt tells the model not to invent environment-specific indexes, sourcetypes, macros, or CIM data models unless they appear in the alert or retrieved SOC context. Generated SPL fields are validated and merged back into the report only when the contract passes.

### 7. Read-Only Splunk Query Execution

When `INVESTIGATION_QUERY_EXECUTION_ENABLED=true`, the service extracts generated hypothesis queries and attempts bounded read-only execution through the configured executor.

The REST executor uses the Splunk oneshot search endpoint by default:

```text
/services/search/jobs/oneshot
```

Before execution, each query is checked against deterministic policy:

- An explicit `index=...` is required.
- Indexes must be in the configured allowlist.
- Denied commands such as destructive, writeback, script, or REST operations are blocked.
- Query time range, row count, timeout, and number of queries are capped.

Execution results are summarized separately in the report. Query results are not promoted into direct evidence for the original notable.

### 8. Report Generation

The service generates a markdown report under `REPORT_DIR`, which defaults to:

```text
/var/notables/reports
```

The report can include:

- Alert reconciliation.
- Competing hypotheses and pivots.
- Optional SPL query details.
- Optional query result summaries.
- Optional ServiceNow draft/create status.
- Evidence versus inference.
- Indicators of compromise.
- Scored ATT&CK techniques grouped by confidence.
- Raw model output only when structured validation failed and human review is needed.

### 9. Splunk Writeback

When `SPLUNK_SINK_ENABLED=true`, the service posts the generated markdown report back to Splunk ES as a notable comment. The writeback identifier is derived from the input filename stem and sent as `finding_id`.

This writeback is separate from read-only investigation query execution. Splunk writeback updates the notable comment; investigation query execution runs bounded searches and summarizes results.

### 10. ServiceNow Draft and Create

When `SERVICENOW_DRAFT_ENABLED=true`, the service can build a ServiceNow incident draft payload from the analysis result. The draft includes short description, description, assignment group, category, impact, urgency, correlation ID, and work notes.

When `SERVICENOW_CREATE_ENABLED=true`, the service can create an incident through the ServiceNow REST API. By default, create is approval-gated with `SERVICENOW_CREATE_REQUIRES_APPROVAL=true`. Approval metadata must be present in the incoming JSON payload before the create operation is allowed.

If approval is missing or invalid, create fails closed and the report records the denied status.

### 11. File Movement and Retention

Successful inputs are moved to `PROCESSED_DIR`. Failed, empty, invalid, or unprocessable inputs are moved to `QUARANTINE_DIR` with a logged reason.

Retention is two-stage:

1. Processed files, quarantined files, and reports are moved into `ARCHIVE_DIR`.
2. Archived files are deleted after the configured archive retention window.

Retention can run inside the analyzer service or be moved to a systemd timer.

## On-Prem Architecture

The core deployment uses a single-host RHEL-oriented architecture:

- `vllm.service` serves the local model on loopback, with `litellm.service` exposing the analyzer-facing OpenAI-compatible gateway.
- `notable-analyzer.service` polls for notable files and orchestrates analysis.
- `/etc/notable-analyzer/config.env` controls runtime capabilities.
- `/var/notables/incoming` receives inputs.
- `/var/notables/reports` stores generated markdown reports.
- `/var/notables/processed`, `/var/notables/quarantine`, and `/var/notables/archive` support operations and retention.
- Optional RAG source documents and ingest reports live under `/opt/llm-notable-analysis/knowledge_base`; production retrieval uses the configured PostgreSQL/pgvector table.
- Optional Splunk and ServiceNow integrations use outbound HTTPS from the analyzer host.

## Operating Modes

### Base Analysis Mode

Base mode runs local LLM analysis, validates ATT&CK IDs, writes a markdown report, and moves the input file to processed or quarantine. This is the safest first deployment mode.

### RAG-Grounded Analysis Mode

RAG mode adds local operational context from SOPs, Splunk references, and other knowledge-base documents. It improves environment awareness but remains advisory.

### SPL Generation Mode

SPL generation mode adds one query per hypothesis for analyst investigation. It does not execute the queries by itself.

### Read-Only Investigation Mode

Read-only investigation mode executes policy-approved generated queries and adds compact query result summaries to the report.

### Splunk Writeback Mode

Splunk writeback posts the markdown report to the originating Splunk notable as a comment.

### ServiceNow Mode

ServiceNow mode creates incident drafts and can optionally create incidents through an approval-gated REST call.

## Security and Control Posture

The current workflow includes controls appropriate for on-prem deployment:

- vLLM binds to loopback by default.
- Services run as dedicated users.
- systemd hardening limits filesystem and process privileges.
- The analyzer writes only to configured data paths.
- Secrets and runtime settings live in `/etc/notable-analyzer/config.env`, not in code.
- Splunk TLS verification is enabled by default and can use an internal CA bundle.
- ServiceNow create requires HTTPS and, by default, explicit payload-level approval.
- Query execution is read-only, allowlisted, denylisted, time-bounded, row-bounded, and timeout-bounded.
- RAG content is advisory and not direct evidence.
- ATT&CK technique IDs are filtered through a local allowlist.
- Failed inputs are quarantined instead of silently discarded.

## Observability and Validation

Operators validate and monitor the service with standard Linux tooling:

- `systemctl status notable-analyzer`
- `systemctl status vllm`
- `journalctl -u notable-analyzer -f`
- `journalctl -u vllm -f`
- Report files under `/var/notables/reports`
- Processed and quarantined input files under `/var/notables`
- Optional Splunk notable comments
- Optional ServiceNow incident numbers and sys_ids in the report

Automated unit tests cover ingestion, formatting, LLM contracts, SPL generation, query execution policy, ServiceNow behavior, markdown rendering, and main-loop integration paths. They do not require vLLM or the analyzer service to be running.

## Key Readiness Constraints

Before production rollout, the customer environment must validate:

- The selected local model is present and approved for use.
- vLLM model path, served model name, and `LLM_MODEL_NAME` match.
- GPU, CPU, RAM, and disk sizing match expected notable volume and latency needs.
- SFTP or other file-drop transport is hardened and audited.
- RAG source documents are curated, current, and approved for analyst use.
- Splunk index allowlists, denied commands, time bounds, and REST endpoint paths match customer policy.
- Splunk writeback identifier mapping is confirmed with the Splunk team.
- ServiceNow assignment group, token, endpoint, and approval workflow are confirmed before enabling create.
- Retention settings match data-handling and audit requirements.

## Success Criteria

A successful end-to-end run is complete when:

1. A `.json` or `.txt` notable lands in the incoming directory.
2. The analyzer picks it up during the next poll cycle.
3. Local LLM analysis completes or produces a reviewable fallback.
4. ATT&CK IDs are validated and invalid techniques are filtered.
5. Optional RAG, SPL, Splunk execution, Splunk writeback, and ServiceNow steps run only when enabled.
6. A markdown report appears in the report directory.
7. The input file is moved to processed or quarantine.
8. Operators can trace the run through journald logs and output files.

## Current Recommended Rollout Path

Start with base analysis mode using local Gemma or GPT-OSS through vLLM. Validate report quality, service stability, file movement, retention, and logs with representative notables. Then enable RAG with curated SOP and Splunk reference documents. After RAG quality is validated, enable SPL generation. Enable read-only Splunk execution only after query policy has been reviewed with the Splunk team. Enable Splunk writeback and ServiceNow draft/create as separate steps, with ServiceNow create left approval-gated.
