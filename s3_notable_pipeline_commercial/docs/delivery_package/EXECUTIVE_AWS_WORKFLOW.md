# Executive AWS Workflow

How a notable moves from customer detection and SOAR handoff through serverless
AWS analysis to analyst-ready reports in S3. This is the **workflow companion**
to
[`AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md`](AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md),
which summarizes readiness buckets, ownership, and what rollout assumes.

For visual flowcharts, see
[`end_to_end_diagrams/END_TO_END_DIAGRAMS.md`](end_to_end_diagrams/END_TO_END_DIAGRAMS.md).
For operator tuning, see [`../operations/README.md`](../operations/README.md).

## Executive Summary

When a correlation search or SOAR workflow produces a notable, the customer
uploads one bundled alert file to an S3 input bucket. S3 triggers a Lambda
function that reads the payload, calls Amazon Bedrock for structured analysis,
validates the response, and writes markdown and JSON reports (and optional HTML)
to an S3 output bucket.

Optional profiles can add Bedrock Knowledge Base context, read-only Splunk or
Elasticsearch hunt queries, ServiceNow drafts, Splunk notable comment writeback,
ServiceNow incident create behind approval gates, and a read-only analyst portal
with case archive. Those steps are additive; the base path is upload in, reports
out.

This is analyst-assist only. It does not autonomously close, suppress,
escalate, contain, or remediate alerts.

## End-to-End Flow

### 1. Upstream: detection and handoff

Customers typically alert on thresholds per user or host. When a threshold
trips, correlation searches gather nearby context and Splunk ES or SOAR produces
one bundled notable payload. The AWS pipeline does not replace that stack; it
processes what the customer already decided is worth analyzing.

Common handoff paths:

- SOAR or Splunk workflow uploads one JSON file per notable to the input bucket
  under `incoming/`
- An operator uploads a test file manually for replay or pilot validation

Preferred delivery is one complete payload per notable. The Lambda handler skips
empty objects, folder markers, and common placeholder keys so partial or
accidental uploads do not start analysis runs.

### 2. Intake and trigger

The input bucket is configured to invoke Lambda when a new object appears under
`incoming/`. Each object represents one notable. The function reads and
normalizes the payload as JSON or plain text while preserving the original alert
content for analysis.

By default each upload produces one analysis run and one report set. This keeps
the workflow simple to deploy, review, monitor, and validate before broader
automation is added.

### 3. Cloud analysis

The function sends the normalized alert to Amazon Bedrock using a constrained
cybersecurity analysis prompt. The model returns a structured investigation
package:

- Alert reconciliation with confidence
- Direct evidence separated from inference
- Competing hypotheses with investigation pivots
- IOCs and MITRE ATT&CK technique mappings

Structured output is parsed, repaired when possible, and validated before use.
Technique IDs are checked against an approved local allowlist. When validation
cannot be completed, raw model output is preserved in a review section instead
of being promoted as trusted analysis.

AI is used for synthesis and explanation. Ingest rules, validation, query
policy, sink routing, idempotency, retention, and side-effect gates stay
deterministic.

### 4. Optional enrichment (customer-selected profiles)

Customers enable optional behavior one profile at a time after non-production
validation. Default deployment is core analysis with reports written only to S3
(`SplunkSinkMode=s3`).

| Profile | What it adds to the workflow |
| --- | --- |
| `html_reports` | A static HTML dashboard alongside markdown and JSON in S3 |
| `rag` | Advisory SOC knowledge-base context in the analysis prompt (not alert evidence) |
| `spl_readonly` | Generated Splunk queries and bounded read-only search against approved indexes |
| `elastic_readonly` | Generated Elasticsearch queries and bounded read-only search (one investigation backend per deployment) |
| `ticket_draft` | ServiceNow incident draft content in the JSON report (no ServiceNow POST) |
| `action_gated` | Splunk notable comment writeback (with `SplunkSinkMode=notable_rest`), approval-gated ServiceNow create, and DynamoDB side-effect idempotency |
| `analyst_portal` | S3 case archive, DynamoDB case index, read-only portal API, and citation-bound case Q&A |

Important boundaries:

- Knowledge-base and query-grounding content is advisory; it does not replace
  facts from the alert or approved query results.
- Read-only investigation stays within customer-approved scope, timeouts, and
  row limits.
- Splunk and Elasticsearch remain authoritative on permissions and query behavior.
- ServiceNow create and Splunk writeback require explicit customer approval
  before enablement. New production writeback rollouts should use `action_gated`.

Set profiles at deploy time via `CapabilityProfiles` / `CAPABILITY_PROFILES`.
See [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md)
for operator detail.

### 5. Outputs and object lifecycle

Each successful run produces at minimum markdown and JSON reports under
`s3://<output-bucket>/reports/`. When enabled, an HTML report, Splunk notable
comment, ServiceNow draft or ticket, and archived case record may also be
written.

After processing:

- Input objects remain in the input bucket until lifecycle rules expire them
- Reports in the output bucket follow customer retention policy
- Optional side effects (Splunk comments, ServiceNow creates) run only through
  configured profiles and approval gates

An optional read-only analyst portal lets reviewers browse archived cases and
ask bounded questions over stored analysis. It does not drive autonomous
response actions.

## What the Analyst Receives

A complete first-pass investigation package stored in the customer AWS account:

- Reconciled verdict and confidence guidance
- Evidence vs inference clearly separated
- Competing hypotheses and pivots for follow-up
- IOCs and validated ATT&CK mappings
- Optional hunt-query results and narrative interpretation
- Optional ticketing draft or approved ticket creation
- Optional Splunk notable comment for SIEM-side review

Analysts remain accountable for triage, escalation, and closure decisions.

## Architecture (serverless)

```text
notable upload -> S3 incoming/
  -> Lambda (S3 event)
  -> Amazon Bedrock (+ optional Knowledge Base retrieve)
  -> validated structured report -> S3 reports/
  -> optional Splunk / ServiceNow / case archive / portal
```

Deploy parameters, IAM scope, image publish order, and integration wiring are
documented in the readiness and operations guides. Customer secrets and
integration endpoints stay outside the source repository.

## Security and Trust Model

- Processing runs in the customer AWS account; alert content transits S3,
  Lambda, and Bedrock within that boundary
- Integration credentials live in AWS Secrets Manager; mapping rules and
  allowlists are customer-owned
- Capability profiles gate optional features at startup; unknown profile names
  fail validation
- Generated queries and writebacks pass policy checks before execution
- Failed structured validation preserves reviewable output instead of silently
  accepting bad analysis
- External writes use explicit approval boundaries and DynamoDB idempotency
  where configured
- Enabled profiles should each have a named owner and rollback plan

## Recommended Rollout

Mirror the readiness overview: prove the base path before adding optional
profiles.

1. **Core path** — deploy with `core` and `SplunkSinkMode=s3`, upload
   representative notables, confirm report quality in S3 and CloudWatch logs.
2. **Grounding** — enable knowledge-base context with curated customer SOPs and
   reference material; validate advisory quality.
3. **Investigation aids** — enable Splunk or Elasticsearch read-only search with
   platform-owner approval on scope and load.
4. **Actions** — enable ticketing drafts, then writeback and create only after
   Splunk and ServiceNow owners sign off; prefer `action_gated` for production
   external writes.
5. **Portal (optional)** — enable case archive and portal access after identity,
   network, and archive retention expectations are accepted.

## Success Criteria

A production-ready workflow means:

- A known-good notable produces complete reports in the output bucket
- Failed or malformed inputs are observable in logs without silent success
- Every enabled profile has an owner, validation plan, and rollback plan
- Splunk, ServiceNow, and portal integrations match customer approval boundaries
- Retention and audit expectations are agreed with security and SOC leadership

Pre-production checklist:
[`AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md).

## Where to Go Next

| Need | Document |
| --- | --- |
| Readiness gateway and ownership | [`AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md`](AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md) |
| Detailed readiness checklist | [`AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md) |
| Visual end-to-end diagrams | [`end_to_end_diagrams/END_TO_END_DIAGRAMS.md`](end_to_end_diagrams/END_TO_END_DIAGRAMS.md) |
| Deploy image and SAM flow | [`../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md), [`../../README.md`](../../README.md) |
| Day-two operations index | [`../operations/README.md`](../operations/README.md) |
| Capability profile detail | [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md) |
| Analyst portal (Wave 2) | [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| SOAR upload pattern | [`../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../integrations/SOAR_PLAYBOOK_PHANTOM.md) |
