# Customer ownership and product scope (commercial AWS)

What the **product IaC creates and operates** versus what **you must
provision, host, or run** in your commercial AWS account (`aws`, `us-east-1`).
Read this during root README **section 3.1** before picking Path A, B, or C.
Use during sales handoff, deployment planning, and security review.

## At a glance

| Category | You own | Stack creates / app runs |
| --- | --- | --- |
| Network + search | VPC, subnets, NAT/routes | Path B Terraform creates or attaches the Lambda SG and OpenSearch domain; index mappings appear after first write |
| Identity + edge | IdP, JWT issuance, browser login, VPN/proxy/firewall to API Gateway, CloudFront/WAF/DNS/TLS if used | API Gateway JWT authorizer config; claim validation in portal Lambda — see [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) |
| Crypto + image | ECR image build/push and release approval | Path B creates or attaches optional CMK and ECR repository; pulls image by digest |
| Data + integrations | Notable source to `incoming/`; Splunk/ServiceNow/Elastic endpoints + secrets; RAG corpus files | S3 buckets (configurable names), queues, CaseIndex DDB, analyzer/ingest/embed logic |
| Ops | Alarms, dashboards, on-call, OpenSearch sizing/ISM/snapshots, staging/prod promotion | CloudWatch logs for product Lambdas; smoke paths in [`../../testing/TESTING.md`](../../testing/TESTING.md) |

## Customer-owned infrastructure and services

These remain **customer-owned** for Path B. Terraform may configure a product
resource inside the customer account, but the customer retains operational and
approval ownership.

| Item | Your responsibility | Operator runbook |
| --- | --- | --- |
| OpenSearch domain | Capacity, backups, access approval; Path B creates or attaches it through customer-owned state | [`../../../deploy/terraform/README.md`](../../../deploy/terraform/README.md), [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) |
| VPC, subnets, NAT, VPC endpoints | Private subnets, routing; Lambda SG via Terraform [`network/`](../../../deploy/terraform/network/) or manual | [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md) |
| JWT / OIDC IdP | Cognito, Okta, Keycloak, Microsoft Entra, or corporate OIDC; API access tokens; Entra API + SPA app registrations when using `entra` SPA mode; analyst role/scope claims | [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) |
| CloudFront, WAF, public DNS, portal TLS | Optional front door in front of API Gateway URL | Not in v1 — see [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Customer CMK (optional) | Key administration and approval; Path B creates or attaches the key and policy | [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) |
| ECR image | Build, push, scan, approve, and record digest; Path B may create the repository | [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) |
| Bedrock model access | Enable models in account; pass ID + ARN | [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md) |
| Upstream notable source | Splunk/SOAR/operator writes JSON to `incoming/` | [`../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md), [`../../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM.md) |
| Splunk / ServiceNow / Elasticsearch | Endpoints, credentials, approval workflows when profiles enabled | [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md), [`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md) |
| RAG corpora | Approved SOPs, Splunk dictionary JSON, manifests in S3 | [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) |

Recovery behavior (retries, DLQ, idempotency): [`../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md).

Release-time ownership, Terraform or legacy SAM gates, live-cloud acceptance, upgrades,
and rollback are in
[`DEPLOYMENT_READINESS_AND_LIFECYCLE.md`](DEPLOYMENT_READINESS_AND_LIFECYCLE.md).

## What Path B Terraform creates

Composed by [`../../../deploy/terraform/customer_default/`](../../../deploy/terraform/customer_default/):

- S3-triggered analyzer Lambda, RAG ingestion, case embed, and portal API
- SQS queues and DLQs for analyzer, embed, and ingestion paths
- S3 buckets for input, output, and portal UI (names you supply)
- DynamoDB CaseIndex table
- Regional API Gateway HTTP API for portal (`/api/*` + static SPA proxy)
- IAM roles and inline policies scoped to customer ARNs (Bedrock, OpenSearch, secrets, KMS)
- CloudWatch log groups for product functions

The stack does **not** create OpenSearch indexes until runtime: `ensure_vector_index()`
creates k-NN indexes on first ingest or case embed.

## Capabilities shipped on AWS (baseline vs opt-in)

P1–P8 parity code is **shipped** on commercial AWS. The customer-default baseline
preset enables core + RAG + analyst portal only; other shipped capabilities stay
off until you opt in.

| Capability | Shipped | In customer-default baseline preset |
| --- | --- | --- |
| Bedrock rerank after OpenSearch hybrid fetch (`RAG_RERANK_ENABLED`) | Yes | No — opt-in |
| Rich KB ingest (PDF, DOCX, images via `IMAGE_INGEST_*`) | Yes | No — opt-in |
| Closed-ticket ServiceNow sync + closed-ticket RAG (P3–P7) | Yes | No — opt-in |
| Portal chat image uploads (`CaseQaChatImagesEnabled`) | Yes | No — opt-in |
| Live Splunk SPL in analysis without `spl_readonly` | Use `spl_readonly` profile or S3-only sink | No |
| Backup, restore, RPO/RTO, cross-region DR | Out of initial release | No |

References:
[`../../planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](../../planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md),
[`../../planning/TODOS.md`](../../planning/TODOS.md),
[`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md),
[`portal_chat_images.py`](../../../src/s3_notable_pipeline/portal_chat_images.py).

## Customer-default deployment (commercial)

Fill the Terraform example for the customer-default bundle:
[`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md) +
[`../../../deploy/terraform/customer_default/`](../../../deploy/terraform/customer_default/).

## Next

- Root README **section 3.2:** [`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md) — customer values checklist
- Root README **section 3.3:** pick **Path A**, **Path B**, or **Path C**
- **Path B:** root README **section 3.4** (prepare Terraform inputs), then [`../../../README.md#path-b--customer-default`](../../../README.md#path-b--customer-default)
- Approved architecture differences: [`../../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md`](../../internal/COMMERCIAL_AWS_APPROVED_DIFFERENCES.md)
