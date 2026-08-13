# Customer ownership and product scope (GovCloud AWS)

What the **product SAM stack creates and operates** versus what **you must
provision, host, or run** in your GovCloud account (`aws-us-gov`, `us-gov-east-1`).

Use this page during sales handoff, deployment planning, and security review.
Detailed runbooks are linked for every customer-owned item we document today.

## At a glance

| Category | You own | Stack creates / app runs |
| --- | --- | --- |
| Network + search | VPC, subnets, NAT/endpoints, OpenSearch domain | Lambda ENI attachment to **your** subnets/SGs; index **mappings** inside **your** domain after first write |
| Identity + edge | IdP, JWT issuance, browser login, VPN/proxy/firewall to API Gateway, CloudFront/WAF/DNS/TLS if used | API Gateway JWT authorizer config; claim validation in portal Lambda |
| Crypto + image | Optional CMK + key policies; ECR build/push | Uses `CustomerKmsKeyArn` when set; pulls image by digest |
| Data + integrations | Notable source to `incoming/`; Splunk/ServiceNow/Elastic endpoints + secrets; RAG corpus files | S3 buckets (configurable names), queues, CaseIndex DDB, analyzer/ingest/embed logic |
| Ops | Alarms, dashboards, on-call, OpenSearch sizing/ISM/snapshots, staging/prod promotion | CloudWatch logs for product Lambdas; documented smoke paths in [`../../testing/TESTING.md`](../../testing/TESTING.md) |

## Infrastructure the stack does not create

These are **customer-owned**. Runbooks describe how to wire values into SAM; the
product does not run CloudFormation or automation for them.

| Item | Your responsibility | Operator runbook |
| --- | --- | --- |
| OpenSearch domain | VPC-only domain, security groups, domain access policy | [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) |
| VPC, subnets, NAT, VPC endpoints | Private subnets, routing, Lambda security groups | [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md) |
| JWT / OIDC IdP | Cognito GovCloud, Okta, Keycloak, or corporate OIDC | [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) |
| CloudFront, WAF, public DNS, portal TLS | Optional front door in front of API Gateway URL | Not in v1 — see [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Customer CMK (optional) | Create key, key policy for Lambda roles + OpenSearch | [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) |
| ECR image | Build, push, record digest for deploy | [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) |
| Bedrock model access | Enable models in account; pass ID + ARN | [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md) |
| Upstream notable source | Splunk/SOAR/operator writes JSON to `incoming/` | [`../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md), [`../../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM.md) |

## What the stack does create (when enabled)

Rendered from [`../../../deploy/aws/template-sam.yaml`](../../../deploy/aws/template-sam.yaml) based on capability flags:

- S3-triggered analyzer Lambda, optional RAG ingestion, case embed, portal API, disposition sync
- SQS queues and DLQs for analyzer, embed, and ingestion paths
- S3 buckets for input, output, and portal UI (names you supply)
- DynamoDB CaseIndex, side-effect idempotency, disposition, and chat history tables when portal/disposition features are on
- Regional API Gateway HTTP API for portal (`/api/*` + static SPA proxy)
- IAM roles and inline policies scoped to customer ARNs (Bedrock, OpenSearch, secrets, KMS)
- CloudWatch log groups for product functions

The stack does **not** create OpenSearch indexes until runtime: `ensure_vector_index()`
in the application creates k-NN indexes on first ingest or case embed.

## Capabilities not shipped on AWS (on-prem may differ)

Intentional product gaps for v1 GovCloud AWS. Do not expect SAM parameters alone
to enable these.

| Capability | Status | Reference |
| --- | --- | --- |
| Closed-ticket ServiceNow sync + closed-ticket RAG | Not shipped | Commercial parity plan (reference only): [`../../../../s3_notable_pipeline_commercial/docs/planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](../../../../s3_notable_pipeline_commercial/docs/planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md) |
| Live Splunk SPL in analysis without `spl_readonly` | Use `spl_readonly` profile or S3-only sink | [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) |
| Portal chat image uploads (backend) | Not shipped | [`../../../../PORTAL_CHATBOT_CAPABILITY_GAPS.md`](../../../../PORTAL_CHATBOT_CAPABILITY_GAPS.md) |
| KB ingest for PDF / DOCX / images | **On-prem shipped** (`IMAGE_INGEST_ENABLED`); **AWS backlog** (text/json/md/txt/csv only) | On-prem: [`IMAGE_INGEST_PREREQUISITES.md`](../../../llm_notable_analysis_onprem_systemd/docs/operations/rag/IMAGE_INGEST_PREREQUISITES.md); AWS: [`../../planning/TODOS.md`](../../planning/TODOS.md) |
| Bedrock rerank as default retrieval step | `RAG_RERANK_ENABLED` not wired in OpenSearch path | Keep off; see [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md) |
| Backup, restore, RPO/RTO, cross-region DR | Out of initial release | [`GOVCLOUD_CUSTOMER_CONFIGURATION.md`](GOVCLOUD_CUSTOMER_CONFIGURATION.md) deployment boundary |

## Portal and auth: validate, do not issue

| Topic | Product behavior | You provide |
| --- | --- | --- |
| Browser login / user provisioning | None | IdP hosted UI or corporate SSO |
| JWT issuance | None | Tokens with `iss`, `aud`, `sub`, and configured role or scope |
| Corporate network access | API Gateway is reachable per AWS networking you configure | VPN, proxy, firewall rules to regional API URL |
| Static SPA hosting | Private S3 UI bucket; Lambda serves assets | Upload built SPA after deploy |

See [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) and
[`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md).

## Integrations the product does not host

| Integration | Product role | You provide |
| --- | --- | --- |
| Splunk | Optional read/write adapters when profiles enabled | HTTPS endpoint, Secrets Manager ARN, network path |
| ServiceNow | Optional ticket draft/create when enabled | Instance URL, credentials, approval workflow |
| Elasticsearch | Optional query generation when `elastic_readonly` enabled | Cluster URL, credentials |
| SIEM/SOAR playbooks | S3 drop contract documented | Phantom or equivalent writes to `incoming/` |
| RAG corpora | Ingestion worker when `RagIngestionEnabled=true` | Approved SOPs, Splunk dictionary JSON, manifests in S3 |

Integration tuning: [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md),
[`../integrations/SERVICENOW_OPERATIONS.md`](../integrations/SERVICENOW_OPERATIONS.md),
[`../../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM.md).

## Operations the product does not run

| Area | You own | Product provides |
| --- | --- | --- |
| Alarm routing, dashboards, on-call | SNS topics, escalation, runbooks | Log streams and queue metrics to monitor |
| OpenSearch capacity, ISM, snapshots | Domain sizing, retention policies | Index auto-create on first write |
| Production promotion | Staging sign-off, change control | Smoke and staging tables in [`../../testing/TESTING.md`](../../testing/TESTING.md) |
| Account-wide patching / org guardrails | Your cloud foundation team | Stack updates via your deploy pipeline |

Recovery behavior: [`../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](../platform/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md).

## GovCloud customer-default preset

GovCloud ships a copy-and-fill SAM preset for the on-prem **customer-default**
bundle (`core,rag,analyst_portal`):

[`GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md)

Preset files: [`../../../deploy/aws/presets/customer-default.env.example`](../../../deploy/aws/presets/customer-default.env.example),
[`../../../deploy/aws/presets/samconfig.customer-default.toml.example`](../../../deploy/aws/presets/samconfig.customer-default.toml.example).

Manual Path B (same bundle without the preset) remains in [`../../README.md`](../../README.md).

Commercial reference (do not deploy into GovCloud):
[`../../../../s3_notable_pipeline_commercial/docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../../../s3_notable_pipeline_commercial/docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)

## Related docs

- Deploy path hub: [`../../README.md`](../../README.md)
- Customer values checklist: [`GOVCLOUD_CUSTOMER_CONFIGURATION.md`](GOVCLOUD_CUSTOMER_CONFIGURATION.md)
