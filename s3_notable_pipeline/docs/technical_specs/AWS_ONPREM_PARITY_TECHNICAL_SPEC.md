# AWS / On-Prem Parity Technical Spec

## Status

Technical-spec shell for the AWS parity implementation. Diff 1 establishes
runtime configuration, centralized AWS client creation, deployment-parameter
scaffolding, and documentation structure. Later diffs must fill in the relevant
sections before implementing each capability.

## Normative Source

The implementation plan is
[`../planning/AWS_ONPREM_PARITY_PLAN.md`](../planning/AWS_ONPREM_PARITY_PLAN.md).
If this spec and the plan conflict before a section is filled in, stop and
resolve the conflict before coding.

## Locked Runtime Shape

The AWS pipeline keeps its current architecture:

```text
S3 incoming object -> Lambda -> Bedrock analysis -> S3 report output -> optional Splunk writeback
```

New capabilities must be inserted as optional, default-off steps around that
flow. Do not move orchestration to Step Functions as part of this parity block.

## Diff 1 Contract

Diff 1 adds:

- `src/s3_notable_pipeline/config.py` for capability profile parsing and runtime
  config validation.
- `src/s3_notable_pipeline/aws_clients.py` for centralized boto3 client creation
  with `AWS_ENDPOINT_URL` support for local emulation.
- `config.env.example` as the operator-readable runtime contract companion to
  SAM/CloudFormation parameters.
- Operations documentation skeletons.
- SAM and pure CloudFormation parameter scaffolding for Lambda resource tuning
  and future profile-driven settings.

Diff 1 must preserve current default behavior:

- `CAPABILITY_PROFILES=core`
- `SPLUNK_SINK_MODE=s3`
- one S3 object triggers one Lambda analysis run
- markdown and JSON outputs are written under `reports/`
- `SPLUNK_SINK_MODE=notable_rest` still writes S3 output first, then posts to
  Splunk REST

## Capability Profiles

Supported profile names:

- `core`
- `html_reports`
- `rag`
- `spl_readonly`
- `elastic_readonly`
- `ticket_draft`
- `action_gated`

Rules:

- `core` is always included.
- Unknown profiles fail configuration validation.
- `spl_readonly` and `elastic_readonly` are mutually exclusive.
- Risky capabilities remain off unless enabled by profile or documented legacy
  low-level flags.

## AWS Client Creation

All new AWS SDK clients must come from `aws_clients.py`.

Unit tests must mock clients and must not require AWS credentials. Local
integration tests, if added later, must use `AWS_ENDPOINT_URL` and local test
credentials.

## Open Sections For Later Diffs

The following sections must be completed in the same diff that implements the
feature:

- Bedrock Knowledge Base retrieval contract.
- HTML report output contract.
- SPL generation and grounding contract.
- Splunk REST/MCP execution contract.
- Query-result enrichment and interpretation contract.
- ServiceNow draft/create contract.
- DynamoDB idempotency contract.
- Elasticsearch generation, grounding, and execution contract.
