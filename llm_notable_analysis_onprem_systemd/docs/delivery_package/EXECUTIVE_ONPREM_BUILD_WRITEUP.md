# Executive On-Prem Build Writeup

## Executive Summary

The on-prem build provides a customer-controlled notable analysis stack for SOC teams that need local AI assistance without sending alert content to an external LLM service. The package combines a local AI inference layer, a `systemd`-managed analyzer application, optional retrieval grounding, and optional security workflow integrations.

The core outcome is a repeatable file-drop workflow: a SOAR platform, SFTP drop, NFS share, or operator places a `.json` or `.txt` notable into an incoming directory; the analyzer runs local LLM analysis; and the system writes a markdown investigation report with evidence, hypotheses, IOCs, ATT&CK mappings, and optional Splunk or ServiceNow outputs.

This is designed as an analyst-assist workflow. It helps prepare a first-pass investigation package, but it does not autonomously close, suppress, escalate, or contain alerts.

## What We Provide

### AI Infrastructure Setup

The on-prem package provides the deployment shape for a local OpenAI-compatible inference path:

- `vLLM` serves the approved local model on the host, defaulting to `gemma-4-31B-it`.
- `LiteLLM` acts as the local proxy and caller-facing control plane, normally bound to `127.0.0.1:4000`.
- The analyzer calls LiteLLM through the OpenAI-compatible chat-completions API.
- Runtime values are managed through `/etc/notable-analyzer/config.env`.
- `systemd` units define how `vLLM`, `LiteLLM`, and the analyzer run on the host.
- Smoke checks validate model serving, LiteLLM routing, and the full analyzer service chain.

The model weights themselves are not included in the repository. The customer or deployment team must stage approved model artifacts on the target host or provide an approved offline transfer process.

### Application Layer

The application is the `notable-analyzer` service. It provides:

- File-drop ingestion for `.json` and `.txt` notables.
- Local LLM analysis with a structured output contract.
- Evidence and inference separation so retrieved guidance or model reasoning is not presented as raw alert evidence.
- Six competing benign/adversary hypotheses with recommended investigation pivots.
- IOC extraction and MITRE ATT&CK technique validation.
- Markdown report generation under the configured reports directory.
- Deterministic movement of input files to processed, quarantine, and archive paths.
- Bounded concurrency controls for larger hosts.

### Optional Grounding And Integrations

The base service works without external integrations. Optional capabilities can be enabled only after the customer validates the related ownership, credentials, policies, and data sources:

- RAG grounding from local SOPs, playbooks, data dictionaries, Splunk field references, and investigation guidance.
- PostgreSQL plus pgvector retrieval for production-oriented RAG, with SQLite plus FAISS available as a smaller fallback option.
- SPL generation for analyst investigation pivots.
- SPL-focused RAG for customer-approved indexes, sourcetypes, macros, fields, and example queries.
- Read-only Splunk query execution with index allowlists, denied command checks, time bounds, row limits, and execution timeouts.
- Query-result interpretation as a separate narrative step that does not change deterministic query facts or confidence scores.
- Splunk notable writeback as a comment or update path when enabled.
- ServiceNow incident draft generation and approval-gated incident creation.

All optional integrations are disabled by default.

### Operations And Delivery Material

The package includes operational material intended to make the build reviewable and supportable:

- Install and offline prestage guidance.
- Runtime configuration examples.
- Security posture and recovery documentation.
- RAG, SPL, Splunk, ServiceNow, retention, and LLM inference operations guides.
- Unit and smoke test guidance.
- Host path, service, and log conventions for day-2 operations.

## Key Assumptions

### Host And Operating Environment

- The target environment provides a supported Linux host with `systemd`.
- Operators have root or equivalent admin access for service users, directories, unit files, and runtime configuration.
- Python 3.12 is available for the analyzer and local runtime paths.
- The default deployment is host-native and RHEL-oriented, though the core concepts can be adapted by the customer.
- The organization has decided whether the host is connected, air-gapped, or serviced through an offline transfer bundle.

### Hardware

- The recommended compute baseline is an Intel Xeon Gold-class server CPU or equivalent.
- `128 GB` of server-grade ECC RAM is the documented baseline; `256 GB` is preferred when the customer wants more headroom for RAG, concurrency, or larger models.
- `500 GB` NVMe storage is the documented minimum; `1 TB` NVMe is the practical baseline when model artifacts, virtual environments, reports, logs, and alternate models are included.
- The GPU baseline assumes an NVIDIA RTX PRO 6000 with `96 GB` VRAM or greater for the default `gemma-4-31B-it` deployment shape.
- NVIDIA driver and CUDA/runtime compatibility must be validated against the pinned `vllm==0.21.0` runtime shape.

### Model And Inference Contract

- The default model identifier is `gemma-4-31B-it`.
- `vLLM`, `LiteLLM`, and the analyzer must agree on the served model name.
- The default analyzer endpoint is `http://127.0.0.1:4000/v1/chat/completions`.
- `LLM_MODEL_NAME`, the LiteLLM model alias, and the vLLM served model name must remain aligned.
- Alternate local models can be used only after the OpenAI-compatible response contract, latency, parse quality, and prompt behavior are validated with representative notables.

### Data, Security, And Ownership

- Production notables, model weights, wheelhouses, customer-specific manifests, and secrets are not committed to the repository.
- Secrets such as the LiteLLM master key, Splunk token, and ServiceNow token are customer-owned and injected through host-managed configuration.
- RAG content is customer-owned advisory context, not direct alert evidence.
- Retention periods, file-drop transport, and audit requirements are approved by the customer.
- Optional Splunk and ServiceNow integrations have named owners before they are enabled.

## Constraints

- The current build is a single-host on-prem deployment pattern, not a high-availability cluster.
- Model latency and throughput depend on the selected model, GPU profile, prompt size, RAG settings, and concurrency configuration.
- Air-gapped deployments require an approved process for staging Python wheels, model artifacts, RAG models, and configuration bundles.
- The application does not include or manage production customer data, production model weights, or long-lived credentials.
- RAG improves environment grounding, but it must not be treated as current-alert evidence.
- Generated SPL is policy-checked, but Splunk remains the authority on syntax, permissions, index availability, and search behavior.
- Read-only Splunk query execution requires customer-approved allowlists, denied command policy, time bounds, row limits, and load expectations.
- Splunk writeback requires customer confirmation of the endpoint, token scope, and identifier mapping.
- ServiceNow create behavior is approval-gated by default and should remain gated until the customer signs off on assignment groups, impact, urgency, and workflow ownership.
- The system supports analyst decision-making; it is not an autonomous response or enforcement platform.

## Recommended Rollout

Start with base file-drop analysis using local LiteLLM and vLLM. Validate service startup, local model routing, report quality, parse/repair behavior, file movement, retention, logs, and smoke tests with representative notables.

After the base workflow is accepted, enable RAG with curated customer-owned SOPs and Splunk reference material. Then enable SPL generation, read-only Splunk execution, Splunk writeback, and ServiceNow behavior as separate controlled steps with explicit customer approval for each capability.

The green state is a host where operators can start the services, verify the local model endpoint, drop a known-good notable, receive a report, trace the run through journald and output files, and explain which optional integrations are enabled or intentionally disabled.
