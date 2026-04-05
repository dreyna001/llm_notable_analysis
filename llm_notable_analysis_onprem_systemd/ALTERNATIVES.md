# Alternatives (Non-OS / Non-Python Dependencies) — On-Prem Notable Analyzer

This document lists **practical alternatives** to key external components used or implied by `llm_notable_analysis_onprem_systemd/`, focused on **on‑prem / air‑gapped / regulated** deployments.

> Scope: alternatives to **LLM serving/inference**, **artifact distribution**, **ingest/transport**, **secrets**, **logging/telemetry**, and **SBOM/provenance**. (Not a recommendation; depends on enclave standards and accreditation.)

## LLM serving / inference engine (currently: vLLM, OpenAI-compatible HTTP)

- **NVIDIA Triton Inference Server**
  - Best when your org already standardizes on Triton; strong enterprise GPU serving patterns.
  - Tradeoff: less “OpenAI API compatibility” out of the box; more model packaging work.

- **Text Generation Inference (TGI)**
  - Common for Hugging Face–style serving; good throughput for supported architectures.
  - Tradeoff: API/behavior differs from vLLM; integration changes.

- **llama.cpp server**
  - Strong for CPU-only or smaller quantized models (GGUF); simple footprint.
  - Tradeoff: may not meet performance needs for very large models / high throughput.

- **Ollama**
  - Very easy “appliance-like” local model management/serving.
  - Tradeoff: org acceptance varies; less transparent supply-chain controls unless you lock down model sources.

- **TensorRT-LLM**
  - High performance on NVIDIA GPUs; best for tightly optimized, fixed model deployments.
  - Tradeoff: build/packaging complexity; “appliance” workflow may be heavier.

## Model format / artifact management (weights and updates)

- **Internal artifact repository** (preferred for air-gapped)
  - Examples: Nexus, Artifactory, Harbor (OCI artifacts), or an enclave-managed repo.
  - Benefits: approvals, immutability, retention, audit logs, controlled promotion.

- **OCI registry as a universal artifact store**
  - Store model weights, wheels, SBOMs, and evidence bundles as signed OCI artifacts.
  - Benefits: standard distribution channel, works well with signing/attestations.

## Transport / ingest (currently: SFTP file drop)

- **Message bus / queue ingest**
  - Examples: RabbitMQ, Kafka, NATS.
  - Benefits: durable delivery, backpressure, auditability, multi-producer support.
  - Tradeoff: adds infra and operational overhead; requires secure authN/Z.

- **HTTP ingest endpoint**
  - Benefits: simpler than queues; can enforce mTLS, authZ, schemas.
  - Tradeoff: expands attack surface; needs rate limiting, input validation, and WAF-ish controls.

- **Shared storage ingest**
  - Examples: NFS/SMB (already discussed as an alternative).
  - Benefits: leverages enterprise storage controls.
  - Tradeoff: broader network surface; permissions/UID mapping complexity.

## Secrets management (currently: env file on disk)

- **HashiCorp Vault**
  - Strong auditability, dynamic credentials, enterprise patterns.
  - Tradeoff: another critical service; needs HA/backup in serious deployments.

- **CyberArk / Delinea / enterprise PAM**
  - If the org already uses a PAM/secret store, integrate there for tokens/keys.

- **Systemd credentials**
  - Use systemd’s credential injection rather than environment files for secrets.
  - Benefits: keeps secrets out of process env and reduces accidental exposure.

## Logging / telemetry (currently: journald JSON logs)

- **Forwarding agents**
  - Fluent Bit / Fluentd / rsyslog / syslog-ng.
  - Benefits: reliable forwarding, filtering/redaction, TLS to SIEM, buffering.

- **OpenTelemetry collector**
  - Benefits: consistent traces/metrics/logs pipeline, vendor-neutral export.
  - Tradeoff: more moving parts; ensure it fits enclave standards.

## SBOM / provenance / signing (currently: evidence bundle + optional Syft hook)

- **SBOM generation**
  - Syft is common; org may prefer Trivy SBOM or enterprise scanners.
  - Key requirement: generate SBOMs from *actual installed* artifacts or a reproducible build environment.

- **Signing / provenance**
  - Sigstore/cosign (common in OCI registry workflows) for signing artifacts and attestations.
  - GPG-based signing if that is the enclave standard.
  - Key requirement: signatures + immutable storage + documented promotion process.

## Containerization (optional alternative deployment model)

- **Podman + systemd** (rootless where possible)
  - Common in RHEL ecosystems; can reduce host pollution and improve portability.
  - Tradeoff: GPU enablement and performance tuning can be more involved.

- **Kubernetes/OpenShift**
  - Best if you already have an enclave cluster and want standardized operations.
  - Tradeoff: significantly more complexity; often requires dedicated platform team.

