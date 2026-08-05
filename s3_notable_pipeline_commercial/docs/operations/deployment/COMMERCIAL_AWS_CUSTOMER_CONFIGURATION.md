# Commercial AWS Customer Configuration

This runbook defines the values collected for each customer deployment. The
application, templates, queues, indexes, validation, and operational controls
remain product-owned; only customer-specific identifiers, policies, content,
and capacity values change.

## Deployment Boundary

- Region: `us-east-1`
- Partition: `aws`
- One deployment and data boundary per customer
- One immutable ECR image digest per release
- No cross-region data flow in the initial release
- No backup, restore, RPO, or RTO claim in the initial release

## Required Customer Values

These values operationalize the product but do not alter the approved product
differences recorded in
[`../../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md`](../../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md).

| Area | Values collected during operationalization |
| --- | --- |
| Account | Commercial AWS account ID, deployment role, stack name, ECR repository |
| Identity | OIDC issuer, audience, analyst application role and/or delegated scope |
| Deployment scope | Stable deployment/tenant identifier used on every OpenSearch document and query |
| Network | VPC, private subnets, Lambda security groups, private DNS, VPN or Direct Connect routes |
| Encryption | Customer-managed KMS keys and key-administration roles |
| Models | Approved Bedrock analysis, chat, and embedding model IDs available in `us-east-1` |
| Integrations | Private Splunk, ServiceNow, or Elasticsearch endpoints and Secrets Manager ARNs |
| Browser edge | CORS origins, API throttles, reserved concurrency, user quotas, and customer network access controls |
| Retention | Input, report, case, chat, log, queue, DLQ, and OpenSearch retention values |
| Operations | Alarm destinations, dashboards, support ownership, redrive approvers |
| Capacity | Expected notable burst, concurrent analysts, case count, and corpus size |

Deployment must fail validation when an enabled capability is missing one of
its required customer values. Empty strings must not silently enable a public,
shared, or unscoped fallback.

## RAG Corpora

Approved source documents are versioned in customer S3. The ingestion workflow
validates, chunks, embeds, and writes retrieval documents to separate indexes in
the deployment's private OpenSearch domain.

| Corpus lane | Runtime use | Required content |
| --- | --- | --- |
| `soc_operational_knowledge` | Initial alert analysis and optional chat context | Triage SOPs, escalation guidance, detection notes, approved pivots |
| `splunk_data_dictionary` | SPL generation only | Indexes, sourcetypes, fields/types, CIM models, macros, lookups, approved examples |
| `case_chunks` | Selected-case chatbot evidence | Generated immutable case-analysis chunks with S3 provenance |
| `elastic_data_dictionary` | Elasticsearch query generation only | Index patterns, fields/types, timestamp rules, approved DSL examples |

Customer source content changes do not require application code changes. A
source update produces a new manifest/version. The worker tombstones prior
chunks for each source and then indexes deterministic replacement IDs; retries
converge without duplicate active chunks. Reconciliation is required before a
new corpus version is promoted for analyst use.

## SIEM Dictionary Onboarding

1. Customer exports or authors an approved JSON, YAML, Markdown, or text corpus.
2. Operator validates ownership, classification, file type, size, and checksum.
3. Operator uploads it under the configured S3 source prefix with versioning enabled.
4. Operator uploads the approved manifest under `RagManifestPrefix`; S3 publishes that exact manifest version to the ingestion queue.
5. The ingestion worker chunks and embeds the approved content with the configured model.
6. The worker writes tenant-scoped vectors and provenance to the Splunk dictionary index.
7. Reconciliation confirms manifest, source versions, and OpenSearch chunks match.
8. A representative alert verifies grounded SPL uses only approved customer tokens.

The dictionary is advisory query-construction context. It does not prove that a
case event occurred and cannot be promoted to direct alert evidence.

## Promotion Evidence

Record these values for every release:

- rendered CloudFormation template and change set
- image repository, immutable tag, and digest
- region, account, stack, and deployment/tenant identifier
- model and embedding IDs
- OpenSearch endpoint and index aliases, without credentials
- enabled capability profiles
- queue, DLQ, retry, and concurrency settings
- KMS key ARNs and VPC resource IDs
- retention settings and alarm destinations
- smoke-test, failure-injection, redrive, and rollback results
