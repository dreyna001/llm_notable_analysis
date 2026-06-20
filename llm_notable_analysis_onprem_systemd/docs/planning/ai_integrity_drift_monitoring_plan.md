# AI Integrity And Drift Monitoring Plan

## Status

Planning document for a future `llm_notable_analysis_onprem_systemd` integrity
and drift-monitoring layer. **Not implemented** — no runtime contract, systemd
unit, or Evidently dependency exists yet.

## Current Codebase (Baseline)

Use this as the starting point for the first slice. Do not assume these pieces
are wired into drift reporting today.

| Area | Shipped today | Not shipped |
|------|---------------|-------------|
| Analyzer structured output | Validated JSON with verdict, confidence, IOCs, ATT&CK/TTP fields, evidence-vs-inference separation | Centralized drift export or aggregation |
| RAG / SPL / Elastic KB | Manual ingest with `ingest_report.json` under operator KB index dirs; embedding/reranker model ids in `config.env` | Approved manifest comparison or automated hash gate |
| Case archive | Postgres case rows when `analyst_portal` profile is enabled (`verdict`, `confidence`, `search_name`, `risk_score`, `threat_category`, `capability_snapshot`, full `analysis` JSONB) | Eval or integrity artifact paths |
| Portal Case Q&A | Read-only chat with `answer_status` (`answered`, `unknown`, `refused`); citations stripped from API responses | Chat retrieval metrics export for drift dashboards |
| Retention | `notable-retention.timer` for filesystem and case/chat cleanup | `notable-ai-integrity.timer` or `notable-eval.timer` |
| Release evidence | [`scripts/tools/generate_dependency_manifest.sh`](../../scripts/tools/generate_dependency_manifest.sh) captures OS, venv inventories, systemd unit hashes, and model SHA256 when run manually | Install-time approved manifest generation or preflight gate |
| Quality regression | Unit/contract tests, smoke scripts, inference benchmarking | [Golden evaluation harness](golden_eval_harness_todo.md) |

Evidently is **proposed**, not present in Python dependencies or scripts.

## Goal

Keep the first version simple: prove that the on-prem analyzer is running the
approved model, prompt pack, configuration, knowledge base, and retrieval setup,
then run lightweight drift and quality checks on a regular cadence.

This complements the [golden evaluation harness TODO](golden_eval_harness_todo.md):

- **Integrity monitoring** asks whether the deployed artifacts changed.
- **Drift monitoring** asks whether inputs, retrieval, or outputs changed in a
  way operators should review.
- **Golden evaluation** asks whether known cases still produce grounded,
  acceptable answers.

## Simple Target Stack

Use three layers first:

1. **Manifest and hash checks**
   - Model files / model revision
   - Tokenizer files
   - Prompt templates / prompt pack
   - `config.env` runtime contract values, excluding secrets (compare against
     [`CAPABILITY_PROFILES`](../operations/platform/CAPABILITY_PROFILES.md)
     and profile-derived flags)
   - RAG/SPL/Elastic KB source manifests and [`ingest_report.json`](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) artifacts
   - Embedding and reranker model identifiers (`RAG_EMBEDDING_MODEL`,
     `RAG_RERANK_MODEL`, `CASE_QA_EMBEDDING_MODEL`, etc.)
   - App/package version and service image or wheel hash
   - Extend or normalize output from
     [`generate_dependency_manifest.sh`](../../scripts/tools/generate_dependency_manifest.sh)
     rather than inventing a parallel manifest format without review

2. **Evidently reports** (new dependency)
   - Run batch reports over eval inputs, recent notables, retrieval metadata, and
     structured analyzer outputs.
   - Track changes in input field presence, alert categories, entities, verdicts,
     confidence bands, token counts, retrieved-source counts, no-match rates,
     validation failures, and latency.
   - Store reports as operator-reviewed artifacts, not as a blocker for the live
     analyzer path by default.

3. **Golden eval harness**
   - Reuse the planned golden corpus and assistant Q&A checks from
     [golden_eval_harness_todo.md](golden_eval_harness_todo.md).
   - Include weak retrieval, no-match, hallucination, bad-analysis, and weekly
     summary cases.
   - Record the same manifest identifiers used by the integrity layer.

## First-Slice TODO

- Produce an approved deployment manifest during install or release packaging
  (build on `generate_dependency_manifest.sh` output shape).
- Add a preflight command that verifies model, tokenizer, prompt, KB manifest,
  and application hashes before an operator enables monitoring.
- Add a read-only drift job that exports recent structured metadata and runs an
  Evidently report.
- Add a weekly operator command first; later optionally wrap it in
  `notable-ai-integrity.timer` or fold it into a future `notable-eval.timer`
  (distinct from shipped [`notable-retention.timer`](../../deploy/systemd/notable-retention.timer)).
- Emit a short human summary plus a machine-readable JSON report.
- Keep results under an operator-controlled path such as
  `/var/notables/eval/` or `/var/notables/integrity/` (new dirs; not in
  [`config.env.example`](../../config.env.example) today).

## Evidently Inputs To Track

### Available today (needs export job)

From validated analysis JSON, markdown/HTML reports, case archive rows, and
filesystem quarantine counts:

- notable type, source, search name, severity, risk score, and alert category
  (alert payload and case archive facets when present)
- entity counts for hosts, users, IPs, domains, hashes, and URLs (from `analysis`
  IOC sections)
- verdict and confidence distribution
- ATT&CK technique IDs and score bands (from TTP analysis)
- report length and model id (from config and report metadata)
- portal chat `answer_status` distribution when `analyst_portal` is enabled

### Needs new instrumentation or log parsing

Not aggregated for drift reporting today:

- RAG/SPL retrieval source count, snippet count, and no-match rate per analysis
- validation, parse-repair, quarantine, and raw-output fallback counts
- token counts and end-to-end analysis latency (partially logged; not exported)
- portal chat retrieval lane counts, chunk counts, and internal citation coverage
  (API responses intentionally omit citations per
  [analyst portal case archive spec](../technical_specs/analyst_portal_case_archive_technical_spec.md))

## Integrity Checks

The monitoring job should flag, and optionally fail in strict mode, when:

- model or tokenizer hash differs from the approved manifest
- prompt pack hash differs from the approved manifest
- RAG/SPL/Elastic KB source manifest or ingest report hash differs unexpectedly
- embedding/reranker model identifiers differ from the KB build metadata
- `config.env` runtime contract values drift outside approved profiles
- vLLM, LiteLLM, analyzer package, or Python environment versions differ from
  the recorded release manifest

Secrets must never be hashed into reports in plaintext. Hash only normalized
non-secret runtime contract values or redacted config manifests.

## Prompt And RAG Injection Checks

Keep the first version deterministic and fixture-based:

- Include KB documents and sample notables containing obvious prompt-injection
  strings, such as attempts to override instructions or suppress citations.
- Verify that outputs keep direct evidence, advisory context, and inference
  separate.
- Verify that SOP or KB guidance is cited as advisory context, not presented as
  current-alert fact.
- Verify that weak retrieval returns `unknown` or no-match for portal chat and
  analysis paths that support it.

These checks belong in the golden eval harness; use Evidently to track rates and
trends over time once exports exist.

## Non-Goals

- Do not introduce a large observability platform in the first slice (see
  Langfuse-class tracing in [FUTURE_ENHANCEMENTS_ROADMAP.md](FUTURE_ENHANCEMENTS_ROADMAP.md)).
- Do not add multiple overlapping drift frameworks. Start with Evidently.
- Do not block production analysis on weekly monitoring unless operators
  explicitly enable a strict gate.
- Do not send customer notables, KB content, prompts, or model traces to a hosted
  service by default.
- Do not use LLM self-grading as the only drift or hallucination check.
- Do not conflate inference-only benchmarking
  ([`LLM_INFERENCE_BENCHMARKING.md`](../operations/llm/LLM_INFERENCE_BENCHMARKING.md))
  with analyzer or portal drift monitoring.

## Open Decisions

- Exact manifest format and where approved manifests are stored (extend
  `generate_dependency_manifest.sh` vs new schema).
- Whether preflight hash mismatch should warn, fail, or depend on a strict mode.
- Which metadata fields are safe to include in Evidently reports for each
  customer.
- Whether the first weekly job runs only against golden fixtures or also samples
  recent production outputs (case archive vs report files vs logs).
- How long integrity and drift reports should be retained.
- Whether Evidently stays the default or a stdlib-only stats export is enough for
  v1.

## Related Docs

- [Golden evaluation harness TODO](golden_eval_harness_todo.md)
- [Analyst portal case archive technical spec](../technical_specs/analyst_portal_case_archive_technical_spec.md)
- [Knowledge base operations](../operations/rag/KNOWLEDGE_BASE_OPERATIONS.md)
- [Capability profiles](../operations/platform/CAPABILITY_PROFILES.md)
- [Future enhancements roadmap](FUTURE_ENHANCEMENTS_ROADMAP.md)
