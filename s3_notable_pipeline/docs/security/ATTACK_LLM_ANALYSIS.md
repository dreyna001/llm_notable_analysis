# ATT&CK Grounding and LLM Trust Boundaries in `s3_notable_pipeline`

This note explains how the pipeline keeps LLM analysis constrained and defensible across Wave 1 capabilities.

## Goal

Turn a notable into ATT&CK-oriented output without allowing free-form or unsupported technique IDs, while optional profiles add advisory RAG, read-only investigation, and gated external writes without autonomous remediation.

## Wave 1 Scope And Boundaries

Wave 1 adds optional capability profiles on top of the core S3-triggered Bedrock analysis path. Security-relevant boundaries:

- `core` — structured notable analysis; deterministic parse, repair, schema validation, and ATT&CK allowlist; writes S3 reports only.
- `rag` — advisory SOC context in the prompt; KB retrieve only with snippets labeled advisory, not case facts; no external writes.
- `spl_readonly` — SPL generation and result interpretation; index/command/field allowlists, timeouts, and row limits; validated before read-only REST or MCP execution.
- `elastic_readonly` — Query DSL generation and interpretation; index allowlist, field bounds, HTTPS; validated before read-only `_search`.
- `ticket_draft` — incident draft fields in JSON reports only; no ServiceNow POST.
- `action_gated` — preferred production profile for Splunk notable comment idempotency and ServiceNow create; ServiceNow create still requires approval gates and signed approval metadata.
- `html_reports` — extra S3 artifact from validated analysis; no additional LLM boundary.

Out of scope: autonomous remediation, suppression, escalation, case closure, or ticketing decisions without human approval boundaries configured in the deployment.

**Idempotency:** DynamoDB side-effect idempotency applies only to Splunk notable updates (`finding_id` key) and ServiceNow incident creates (`correlation_id` key). It does not deduplicate S3 report writes, read-only queries, or Bedrock calls.

Profile operator detail: `docs/operations/CAPABILITY_PROFILES.md`. End-to-end flow: `docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md`.

## Guardrails

- Load allowed ATT&CK IDs from `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`.
- Include the allowed ID set in the LLM prompt.
- Parse and normalize model output into a known schema.
- Drop any `ttp_id` that is not in the allowed ATT&CK set.
- Keep `last_llm_response` for reporting/debugging, while only scoring validated TTPs.
- Validate generated Splunk SPL or Elasticsearch Query DSL against deployment allowlists before any read-only execution.
- Treat Bedrock Knowledge Base snippets (SOC RAG, SPL grounding, Elastic grounding) as advisory context, not observed alert evidence.

## Evidence Discipline

- Prompts require evidence-vs-inference separation.
- Unknown/missing context should remain `unknown` instead of being fabricated.
- Confidence is represented numerically and adjusted by evidence quality.
- Read-only investigation results are enrichment for analyst review; they do not override the ingested notable as primary evidence.
- ServiceNow draft or create payloads are derived from validated analysis and explicit approval objects, not from unconstrained model invention of ticket facts.

## Runtime Flow

1. `src/s3_notable_pipeline/lambda_handler.py` reads S3 object content.
2. Optional Bedrock Knowledge Base retrieve injects advisory RAG or query-grounding snippets.
3. `src/s3_notable_pipeline/ttp_analyzer.py` normalizes input and builds the constrained prompt.
4. Bedrock is called with retries/backoff.
5. Optional read-only investigation: generated queries are policy-validated, executed with bounds, and normalized results may feed a follow-on interpretation call.
6. Response is parsed and repaired if needed.
7. TTP IDs are validated against the local ATT&CK dataset.
8. `src/s3_notable_pipeline/markdown_generator.py` (and JSON/HTML paths) render reports from validated analysis.
9. Optional gated side effects: new production Splunk notable comment or ServiceNow create rollouts should use `action_gated`, with DynamoDB idempotency reservations. Legacy Splunk `notable_rest` writeback remains supported for existing deployments.

## Updating ATT&CK IDs

When moving to a newer ATT&CK release:

1. Regenerate `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json` from official ATT&CK data.
2. Keep validator/prompt logic unchanged unless schema requirements changed.
3. Re-run pipeline tests with known alerts and compare outputs.
