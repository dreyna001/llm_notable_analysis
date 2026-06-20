# Executive On-Prem Build Writeup

Stakeholder summary of what the on-prem package delivers, what it assumes, and
how rollout should proceed. For end-to-end behavior see
[`EXECUTIVE_ONPREM_WORKFLOW.md`](EXECUTIVE_ONPREM_WORKFLOW.md). For deployment
readiness see
[`AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md`](AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md).

## Executive Summary

The on-prem build gives SOC teams local AI-assisted notable analysis without
sending alert content to an external LLM. A SOAR platform, SFTP drop, or
operator places a `.json` or `.txt` notable in an incoming directory; the
analyzer runs local inference and writes a markdown investigation report with
evidence, hypotheses, IOCs, ATT&CK mappings, and optional integration outputs.

This is analyst-assist only. It does not autonomously close, suppress,
escalate, or contain alerts.

## What We Provide

### AI infrastructure

Local OpenAI-compatible inference on a single host:

- `vLLM` serves the approved model (default `gemma-4-31B-it`) on loopback
- `LiteLLM` is the caller-facing proxy on `127.0.0.1:4000`
- analyzer calls LiteLLM; runtime values live in `/etc/notable-analyzer/config.env`
- packaged `systemd` units for vLLM, LiteLLM, and `notable-analyzer`
- validation via `scripts/smoke_service_chain.sh`

Model weights are not in the repo. Customers stage approved artifacts or use an
offline transfer process ([`../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md`](../operations/deployment/OFFLINE_PRESTAGE_GUIDE.md)).

### Application layer

The `notable-analyzer` service provides:

- file-drop ingest (`INGEST_MODE=file_drop`) for `.json` and `.txt`
- structured local LLM analysis with evidence vs inference separation
- six competing hypotheses with investigation pivots
- IOC extraction and MITRE ATT&CK technique validation
- markdown reports and deterministic processed/quarantine/archive movement
- bounded concurrency for larger hosts

### Optional capabilities

Enabled through `CAPABILITY_PROFILES` in `config.env` (default `core` only).
Add one profile at a time after customer validation:

| Profile | Capability |
| --- | --- |
| `html_reports` | Static HTML alongside markdown reports |
| `rag` | SOC knowledge-base grounding (Postgres/pgvector production path; SQLite/FAISS lab fallback) |
| `spl_readonly` | SPL generation and bounded read-only Splunk search |
| `elastic_readonly` | Elasticsearch Query DSL generation and read-only search |
| `ticket_draft` | ServiceNow incident draft payloads in reports |
| `action_gated` | Splunk notable writeback and approval-gated ServiceNow create |
| `analyst_portal` | Postgres case archive, read-only portal, and Case Q&A |

See [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).

### Operations material

Install, offline prestage, security posture, recovery, RAG/SPL/Splunk/ServiceNow
ops guides, deployment hardware profiles, and test guidance under `docs/`.

## Key Assumptions

**Host:** Linux with `systemd`, Python 3.12, admin access; connected or
air-gapped delivery decided up front.

**Hardware:** Baseline production shape is 128 GB RAM (256 GB preferred), 1 TB
NVMe (500 GB minimum), and an NVIDIA RTX PRO 6000 96 GB-class GPU or equivalent
for the default model. Driver and CUDA/runtime must match pinned `vllm==0.21.0`.
Host-specific tuning: [`../operations/deployment/deployment_profiles/README.md`](../operations/deployment/deployment_profiles/README.md).

**Inference contract:** `vLLM`, LiteLLM, and `LLM_MODEL_NAME` must agree on
the served model. Default endpoint:
`http://127.0.0.1:4000/v1/chat/completions`. Alternate local models require
validation on representative notables before production use.

**Data and security:** Production notables, weights, wheelhouses, and secrets
are customer-owned and not in the repo. RAG content is advisory context, not
alert evidence. Integration tokens and mapping validation are customer-owned
before profiles that touch Splunk, ServiceNow, or the portal are enabled.

## Constraints

- Single-host pattern, not HA clustering
- Throughput depends on GPU, model, prompt size, RAG, and concurrency settings
- Air-gap requires approved staging of wheels, model artifacts, and optional KB bundles
- Splunk and Elasticsearch remain authoritative on permissions, indexes, and query behavior
- Writeback and ServiceNow create require explicit customer approval and `action_gated`
- Supports analyst decisions; not an autonomous response platform

## Recommended Rollout

1. **Base path:** `scripts/install.sh`, `CAPABILITY_PROFILES=core`, smoke test,
   validate report quality and file movement on representative notables.
2. **Grounding:** enable `rag` with curated customer SOPs and reference material.
3. **Investigation aids:** enable `spl_readonly` and/or `elastic_readonly` with
   approved allowlists and load expectations.
4. **Actions:** enable `ticket_draft`, then `action_gated` writeback/create only
   after Splunk/ServiceNow owners sign off.
5. **Portal (optional):** enable `analyst_portal` after Postgres and network rollout.

Green state: services start cleanly, `smoke_service_chain.sh` passes, a known-good
notable produces a report, runs are traceable in journald and output paths, and
every enabled profile is documented with an owner and rollback plan.
