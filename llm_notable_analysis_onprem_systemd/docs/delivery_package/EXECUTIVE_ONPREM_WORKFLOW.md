# Executive On-Prem Workflow

How a notable moves from customer detection and SOAR handoff through local AI
analysis to analyst-ready outputs on a single on-prem host. This is the
**workflow companion** to
[`EXECUTIVE_ONPREM_BUILD_WRITEUP.md`](EXECUTIVE_ONPREM_BUILD_WRITEUP.md), which
summarizes what the build provides and what rollout assumes.

For visual flowcharts, see
[`end_to_end_diagrams/END_TO_END_DIAGRAMS.md`](end_to_end_diagrams/END_TO_END_DIAGRAMS.md).
For operator tuning, see [`../operations/README.md`](../operations/README.md).

## Executive Summary

When a correlation search or SOAR workflow produces a notable, the customer
delivers one bundled alert file to the analyzer host. The on-prem service reads
that file, runs local inference through LiteLLM and vLLM, and produces a
structured investigation report: verdict, evidence, competing hypotheses, IOCs,
and validated ATT&CK mappings.

Optional profiles can add knowledge-base context, read-only hunt queries,
ticketing drafts, Splunk writeback, and a read-only analyst portal with case
archive. Those steps are additive; the base path is file in, report out.

This is analyst-assist only. It does not autonomously close, suppress,
escalate, or contain alerts.

## End-to-End Flow

### 1. Upstream: detection and handoff

Customers typically alert on thresholds per user or host. When a threshold
trips, correlation searches gather nearby context and Splunk ES or SOAR produces
one bundled notable payload. The on-prem pipeline does not replace that stack; it
processes what the customer already decided is worth analyzing.

Common handoff paths:

- SOAR or Splunk workflow writes one file per notable to the host incoming area
- An operator drops a file manually for replay or pilot validation

Preferred delivery is one complete payload per notable, uploaded atomically so
the analyzer never reads a partial file.

### 2. Intake and queueing

The analyzer watches the incoming directory and picks up new `.json` or `.txt`
files in order. Each file represents one notable. Malformed, empty, or
oversized inputs are moved aside for operator review rather than silently
processed.

By default the host processes one notable at a time. Larger deployments can
enable bounded parallel processing after baseline behavior is accepted.

### 3. Local analysis

The service sends the normalized alert to a local model served on the same host.
The model returns a structured investigation package:

- Alert reconciliation with confidence
- Direct evidence separated from inference
- Six competing hypotheses with investigation pivots
- IOCs and MITRE ATT&CK technique mappings

Structured output is validated before use. Technique IDs are checked against an
approved local allowlist. When validation fails, the run is contained and the
input is quarantined rather than promoted as a trusted report.

AI is used for synthesis and explanation. Ingest rules, validation, query
policy, writeback gates, retention, and file movement stay deterministic.

### 4. Optional enrichment (customer-selected profiles)

Customers enable optional behavior one profile at a time after non-production
validation. Default deployment is core analysis only.

| Profile | What it adds to the workflow |
| --- | --- |
| `html_reports` | A static HTML dashboard alongside the markdown report |
| `rag` | Advisory SOC knowledge-base context in the analysis prompt (not alert evidence) |
| `spl_readonly` | Generated Splunk queries and bounded read-only search against approved indexes |
| `elastic_readonly` | Generated Elasticsearch queries and bounded read-only search (one investigation backend per deployment) |
| `ticket_draft` | ServiceNow incident draft content in the report |
| `action_gated` | Splunk notable comment writeback and approval-gated ServiceNow create |
| `analyst_portal` | Postgres case archive, read-only portal, and Case Q&A over archived cases |

Important boundaries:

- Knowledge-base and query-grounding content is advisory; it does not replace
  facts from the alert or approved query results.
- Read-only investigation stays within customer-approved scope, timeouts, and
  row limits.
- Splunk and Elasticsearch remain authoritative on permissions and query behavior.
- ServiceNow create and Splunk writeback require explicit customer approval
  before enablement.

### 5. Outputs and file lifecycle

Each successful run produces at minimum a markdown report on disk. When enabled,
an HTML report, Splunk comment, ServiceNow draft or ticket, and archived case
record may also be written.

After processing:

- Successful inputs move to a processed area for audit and retention
- Failed inputs move to quarantine for operator review
- Reports and archived artifacts follow customer retention policy

An optional read-only analyst portal lets reviewers browse archived cases and
ask bounded questions over stored analysis. It does not drive autonomous
response actions.

## What the Analyst Receives

A complete first-pass investigation package without sending alert content to an
external LLM:

- Reconciled verdict and confidence guidance
- Evidence vs inference clearly separated
- Competing hypotheses and pivots for follow-up
- IOCs and validated ATT&CK mappings
- Optional hunt-query results and narrative interpretation
- Optional ticketing draft or approved ticket creation
- Optional Splunk notable comment for SIEM-side review

Analysts remain accountable for triage, escalation, and closure decisions.

## Architecture (single host)

```text
notable file drop
  -> on-prem analyzer
  -> local LiteLLM -> local vLLM
  -> validated structured report
  -> processed or quarantine
  -> optional Splunk / ServiceNow / case archive / portal
```

Runtime configuration, paths, and service layout are documented in the install
and operations guides. Model weights and customer secrets stay outside the
source repository.

## Security and Trust Model

- Inference stays on the customer host; alert content does not egress to a cloud LLM
- Integration credentials and mapping rules are customer-owned
- Generated queries and writebacks pass policy checks before execution
- Failed validation quarantines input instead of silently accepting bad output
- Enabled profiles should each have a named owner and rollback plan

## Recommended Rollout

Mirror the build writeup: prove the base path before adding optional profiles.

1. **Core path** — install, drop representative notables, confirm report quality
   and correct processed vs quarantine behavior.
2. **Grounding** — enable knowledge-base context with curated customer SOPs and
   reference material; validate advisory quality.
3. **Investigation aids** — enable Splunk or Elasticsearch read-only search with
   platform-owner approval on scope and load.
4. **Actions** — enable ticketing drafts, then writeback and create only after
   Splunk and ServiceNow owners sign off.
5. **Portal (optional)** — enable case archive and portal access after database
   and network rollout are accepted.

## Success Criteria

A production-ready workflow means:

- A known-good notable produces a complete report on disk
- Bad inputs land in quarantine with observable operator signals
- Every enabled profile has an owner, validation plan, and rollback plan
- Splunk, ServiceNow, and portal integrations match customer approval boundaries
- Retention and audit expectations are agreed with security and SOC leadership

Pre-production checklist:
[`AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_ASSESSMENT.md).

## Where to Go Next

| Need | Document |
| --- | --- |
| What the build includes and assumes | [`EXECUTIVE_ONPREM_BUILD_WRITEUP.md`](EXECUTIVE_ONPREM_BUILD_WRITEUP.md) |
| Readiness gateway and ownership | [`AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md`](AIOPTIMIZED_SOC_ANALYSIS_ONPREM_READINESS_OVERVIEW.md) |
| Visual end-to-end diagrams | [`end_to_end_diagrams/END_TO_END_DIAGRAMS.md`](end_to_end_diagrams/END_TO_END_DIAGRAMS.md) |
| Install and day-two operations | [`../operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md), [`../operations/README.md`](../operations/README.md) |
| Capability profile detail | [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md) |
