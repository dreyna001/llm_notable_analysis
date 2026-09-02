# Commercial AWS Customer Configuration

Values collected for each customer deployment. The application, templates, queues,
indexes, validation, and operational controls remain product-owned; only
customer-specific identifiers, policies, content, and capacity values change.

**Deploy journey:** root README section **3.2** (this checklist), after
[`CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md)
(section 3.1). Path B operators fill
[`../../../deploy/terraform/customer_default/terraform.tfvars.example`](../../../deploy/terraform/customer_default/terraform.tfvars.example)
as each prerequisite runbook completes; authoritative step order:
[`../../README.md#path-b--customer-default`](../../README.md#path-b--customer-default).

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
| Identity | OIDC issuer, audience, analyst application role and/or delegated scope — see [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) |
| Deployment scope | Stable deployment/tenant identifier used on every OpenSearch document and query |
| Network | VPC, private subnets, Lambda security groups — see [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md) |
| OpenSearch | VPC-only domain in `us-east-1`; create or attach it in the same Path B Terraform root — see [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) |
| Encryption | Customer-managed KMS keys — see [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) |
| Models | Approved Bedrock analysis, chat, and embedding model IDs — see [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md) |
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

| Manifest `corpus_id` | Runtime use | Required content |
| --- | --- | --- |
| `soc` | Initial alert analysis and optional chat context | Triage SOPs, escalation guidance, detection notes, approved pivots |
| `spl` | SPL generation only | Indexes, sourcetypes, fields/types, CIM models, macros, lookups, approved examples |
| `case_chunks` | Selected-case chatbot evidence | Generated immutable case-analysis chunks with S3 provenance |
| `elastic` | Elasticsearch query generation only | Index patterns, fields/types, timestamp rules, approved DSL examples |

Ingestion canonicalizes the legacy aliases `soc_knowledge`,
`soc_operational_knowledge`, `splunk`, `spl_dictionary`,
`splunk_data_dictionary`, `elasticsearch`, `elastic_dictionary`, and
`elastic_data_dictionary` to those three stable filter values.

Customer source content changes do not require application code changes. A
source update produces a new manifest/version. The worker tombstones prior
chunks for each source and then indexes deterministic replacement IDs; retries
converge without duplicate active chunks. Reconciliation is required before a
new corpus version is promoted for analyst use.

## SIEM Dictionary Onboarding

1. Customer exports or authors an approved JSON, YAML, Markdown, or text corpus.
2. Operator validates ownership, classification, file type, size, and checksum.
3. Operator uploads it under the configured S3 source prefix with versioning enabled.
4. Operator uploads the approved manifest under `RagManifestPrefix`; ingestion, reconciliation, and validation follow [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md).

The dictionary is advisory query-construction context. It does not prove that a
case event occurred and cannot be promoted to direct alert evidence.

## Promotion Evidence

Record these values for every release:

- reviewed Terraform plan for Path B, or CloudFormation change set for Paths A/C
- image repository, immutable tag, and digest
- region, account, stack, and deployment/tenant identifier
- model and embedding IDs
- OpenSearch endpoint and index aliases, without credentials
- enabled capability profiles
- queue, DLQ, retry, and concurrency settings
- KMS key ARNs and VPC resource IDs
- retention settings and alarm destinations
- smoke-test, failure-injection, redrive, and rollback results

## Next

- Root README **section 3.3:** pick your deploy path
- **Path B:** section **3.4** (create `terraform.tfvars`), then [`../../README.md#path-b--customer-default`](../../README.md#path-b--customer-default)
- Path B Terraform plan/apply: [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
