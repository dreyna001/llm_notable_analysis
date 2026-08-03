# ATT&CK Grounding and LLM Trust Boundaries (AWS Bedrock/Lambda)

Threat-model notes for the S3-triggered `s3_notable_pipeline` on AWS: how Bedrock
analysis stays constrained, how optional capability profiles extend the runtime,
and where human approval gates apply.

Deployment security posture (IAM, Secrets Manager, TLS, external action gates, portal
exposure): [`../operations/security/SECURITY_OPERATIONS.md`](../operations/security/SECURITY_OPERATIONS.md).

## Goal

Turn a notable into ATT&CK-oriented output without allowing free-form or unsupported
technique IDs, while optional profiles add advisory RAG, read-only investigation,
case archive/portal Q&A, and gated external writes without autonomous remediation.

## AWS Runtime Trust Boundaries

Primary data and control flow:

1. **S3 input** — customer-owned bucket; object size is bounded before prompt construction.
2. **Lambda analyzer** — reads input, orchestrates Bedrock and optional integrations;
   loads integration secrets from Secrets Manager at runtime.
3. **Amazon Bedrock** — structured analysis inference; optional Knowledge Base retrieve
   for advisory context only.
4. **S3 output** — markdown, JSON, and optional HTML reports under configured prefixes.
5. **Optional outbound HTTPS** — Splunk, Elasticsearch, or ServiceNow only when the
   matching profile, sink mode, and secrets are enabled; URLs pass HTTPS validation
   before calls.
6. **Optional DynamoDB** — side-effect idempotency for Splunk notable update and
   ServiceNow create; CaseIndex when `analyst_portal` is enabled.

Untrusted inputs: S3 object content, Bedrock model output, Knowledge Base snippets,
generated SPL/Query DSL, and ServiceNow approval payloads. None of these drive
external writes until deterministic validation and configured gates pass.

## Capability Profile Boundaries

Profiles are additive. `core` is included automatically when omitted.
`spl_readonly` and `elastic_readonly` are mutually exclusive.

| Profile | LLM / runtime boundary |
| --- | --- |
| `core` | Structured notable analysis; deterministic parse, repair, schema validation, and ATT&CK allowlist; writes S3 reports only. |
| `html_reports` | Extra S3 HTML artifact from validated analysis; no additional LLM boundary. |
| `rag` | Advisory SOC context in the prompt; Bedrock KB retrieve only; snippets are labeled advisory, not case facts; no external writes. |
| `spl_readonly` | SPL generation and result interpretation; index/command/field allowlists, timeouts, and row limits; validated before read-only REST or MCP execution. |
| `elastic_readonly` | Query DSL generation and interpretation; index allowlist, field bounds, HTTPS; validated before read-only `_search`. |
| `ticket_draft` | ServiceNow incident draft fields in JSON reports only; no ServiceNow POST. |
| `action_gated` | Preferred production profile for external writes: enables ServiceNow create approval path, side-effect idempotency, and Splunk sink eligibility. Splunk notable comment writeback still requires `SplunkSinkMode=notable_rest`. ServiceNow create still requires signed approval metadata. |
| `analyst_portal` | S3 case archive, DynamoDB CaseIndex, read-only portal API, and pinned-case Q&A over retained chunks; no SPL/Elastic execution, ticketing, or remediation from portal routes. |

Out of scope: autonomous remediation, suppression, escalation, case closure, or
ticketing decisions without human approval boundaries configured in the deployment.

**Idempotency:** DynamoDB side-effect idempotency applies only to Splunk notable
updates (`finding_id` key, operation `splunk_notable_update`) and ServiceNow
incident creates (`correlation_id` key, operation `servicenow_incident_create`).
It does not deduplicate S3 report writes, read-only queries, Bedrock calls, or
portal chat synthesis.

Profile operator detail: [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md).
End-to-end flow: [`../delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md`](../delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md).

## LLM Threats And Mitigations

| Threat | Mitigation |
| --- | --- |
| Unsupported or invented ATT&CK technique IDs | Bundled allowlist in `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`; full allowed set injected into the prompt; post-parse `filter_valid_ttps` drops IDs not in the set. |
| Schema drift or malformed JSON | Structured output schema; parse and repair retry; schema, content-policy, and competing-hypotheses validation before scoring. |
| Evidence fabrication | Prompts require evidence-vs-inference separation; unknown context stays `unknown`; confidence is numeric and tied to cited alert fields. |
| RAG or KB snippet treated as alert facts | KB retrieve is advisory-only; snippets are labeled as context, not observed case evidence. |
| Prompt injection via notable content | Input size bounded; model output validated before reports or side effects; integration queries validated against allowlists before execution. |
| Unbounded external query or write | Capability profiles gate features; Splunk/Elastic queries require allowlist validation; ServiceNow create requires approval HMAC; writeback uses idempotency reservations. |

## Guardrails

- Load allowed ATT&CK IDs from `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`.
- Include the allowed ID set in the LLM prompt.
- Parse and normalize model output into a known schema.
- Drop any `ttp_id` that is not in the allowed ATT&CK set.
- Keep `last_llm_response` for reporting/debugging; score and report only validated TTPs.
- Validate generated Splunk SPL or Elasticsearch Query DSL against deployment allowlists before any read-only execution.
- Treat Bedrock Knowledge Base snippets (SOC RAG, SPL grounding, Elastic grounding) as advisory context, not observed alert evidence.

MITRE refresh workflow: [`../operations/platform/MITRE_TTP_OPERATIONS.md`](../operations/platform/MITRE_TTP_OPERATIONS.md).

## Evidence Discipline

- Prompts require evidence-vs-inference separation.
- Unknown/missing context should remain `unknown` instead of being fabricated.
- Confidence is represented numerically and adjusted by evidence quality.
- Read-only investigation results are enrichment for analyst review; they do not override the ingested notable as primary evidence.
- ServiceNow draft or create payloads are derived from validated analysis and explicit approval objects, not from unconstrained model invention of ticket facts.

## Runtime Flow

1. `src/s3_notable_pipeline/lambda_handler.py` reads and bounds S3 object content.
2. Optional Bedrock Knowledge Base retrieve injects advisory RAG or query-grounding snippets.
3. `src/s3_notable_pipeline/ttp_analyzer.py` normalizes input and builds the constrained prompt.
4. Bedrock is called with retries/backoff (tool-use mode with repair fallback).
5. Optional read-only investigation: generated queries are policy-validated, executed with bounds, and normalized results may feed a follow-on interpretation call.
6. Response is parsed, repaired if needed, and validated against schema and content policies.
7. TTP IDs are validated against the local ATT&CK dataset.
8. `src/s3_notable_pipeline/markdown_generator.py` (and JSON/HTML paths) render reports from validated analysis.
9. Optional gated side effects: Splunk notable comment when `SplunkSinkMode=notable_rest` (prefer `action_gated` for idempotency); ServiceNow create when `action_gated` and signed approval pass validation.
10. Optional `analyst_portal`: archive validated case artifacts to S3, index metadata in DynamoDB, serve read-only portal routes and pinned-case chat.

## Updating ATT&CK IDs

When moving to a newer ATT&CK release:

1. Regenerate `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json` from official ATT&CK data (see `scripts/extract_ttp_ids.py`).
2. Keep validator/prompt logic unchanged unless schema requirements changed.
3. Rebuild and redeploy the Lambda container image.
4. Re-run pipeline tests with known alerts and compare outputs.

## Related Docs

- [`../operations/security/SECURITY_OPERATIONS.md`](../operations/security/SECURITY_OPERATIONS.md) — IAM, secrets, TLS, external action gates
- [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md) — profile rollout
- [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — portal auth, CORS, and chat boundaries
