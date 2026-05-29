# AI Integrity And Drift Monitoring Plan

## Status

Planning document for a future `llm_notable_analysis_onprem_systemd` integrity
and drift-monitoring layer. This is not a runtime contract yet.

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
   - `config.env` runtime contract values, excluding secrets
   - RAG/SPL KB source manifests and ingest reports
   - Embedding and reranker model identifiers
   - App/package version and service image or wheel hash

2. **Evidently reports**
   - Run batch reports over eval inputs, recent notables, retrieval metadata, and
     structured analyzer outputs.
   - Track changes in input field presence, alert categories, entities, verdicts,
     confidence bands, token counts, retrieved-source counts, no-match rates,
     validation failures, and latency.
   - Store reports as operator-reviewed artifacts, not as a blocker for the live
     analyzer path by default.

3. **Golden eval harness**
   - Reuse the planned golden corpus and assistant Q&A checks.
   - Include weak retrieval, no-match, hallucination, bad-analysis, and weekly
     summary cases.
   - Record the same manifest identifiers used by the integrity layer.

## First-Slice TODO

- Produce an approved deployment manifest during install or release packaging.
- Add a preflight command that verifies model, tokenizer, prompt, KB manifest,
  and application hashes before an operator enables monitoring.
- Add a read-only drift job that exports recent structured metadata and runs an
  Evidently report.
- Add a weekly operator command first; later optionally wrap it in
  `notable-ai-integrity.timer` or fold it into a future `notable-eval.timer`.
- Emit a short human summary plus a machine-readable JSON report.
- Keep results under an operator-controlled path such as
  `/var/notables/eval/` or `/var/notables/integrity/`.

## Evidently Inputs To Track

Start with fields already available from reports, structured analysis output,
retrieval logs, or future case metadata:

- notable type, source, search name, severity, risk score, and alert category
- entity counts for hosts, users, IPs, domains, hashes, and URLs
- verdict and confidence distribution
- ATT&CK technique IDs and score bands
- RAG/SPL retrieval source count, snippet count, and no-match rate
- validation, parse-repair, quarantine, and raw-output fallback counts
- report length, token counts, latency, and model id
- assistant Q&A source count, citation count, `unknown` / no-match rate, and
  answer length once the Notable Archive Assistant exists

## Integrity Checks

The monitoring job should flag, and optionally fail in strict mode, when:

- model or tokenizer hash differs from the approved manifest
- prompt pack hash differs from the approved manifest
- RAG/SPL KB source manifest or ingest report hash differs unexpectedly
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
- Verify that source citations are present for assistant answers and that weak
  retrieval returns `unknown` or no-match.

These checks can live in the golden eval harness, with Evidently used to track
rates and trends over time.

## Non-Goals

- Do not introduce a large observability platform in the first slice.
- Do not add multiple overlapping drift frameworks. Start with Evidently.
- Do not block production analysis on weekly monitoring unless operators
  explicitly enable a strict gate.
- Do not send customer notables, KB content, prompts, or model traces to a hosted
  service by default.
- Do not use LLM self-grading as the only drift or hallucination check.

## Open Decisions

- Exact manifest format and where approved manifests are stored.
- Whether preflight hash mismatch should warn, fail, or depend on a strict mode.
- Which metadata fields are safe to include in Evidently reports for each
  customer.
- Whether the first weekly job runs only against golden fixtures or also samples
  recent production outputs.
- How long integrity and drift reports should be retained.
