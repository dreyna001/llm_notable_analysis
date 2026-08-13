# AWS Readiness Overview

Executive gateway for the AWS deployment path of `s3_notable_pipeline` (Wave 1
and optional Wave 2). Use this document to decide whether engineer-led deployment
can begin. Use
[`AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md)
for the detailed technical rationale.

**Deploy and operator runbooks:**
[`../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../operations/deployment/DEPLOYMENT_IMAGE_STEPS.md),
[`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md),
[`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).

## In Scope

AWS deployment of `s3_notable_pipeline` through SAM / CloudFormation: Bedrock
analysis, S3 report output, optional capability profiles, and optional analyst
portal stack outputs.

### Shipped on `main` (Wave 1)

Runtime code, SAM/CloudFormation templates, mocked unit tests, and operations
docs for these profiles:

- `core` — S3 ingest, Bedrock analysis, markdown + JSON reports (always included)
- `html_reports` — static HTML reports in S3
- `rag` — advisory SOC context from the deployment's tenant-scoped OpenSearch corpus
- `spl_readonly` — generated SPL and bounded read-only Splunk REST or MCP investigation
- `elastic_readonly` — generated Query DSL and bounded read-only Elasticsearch `_search`
- `ticket_draft` — ServiceNow incident drafts in JSON reports (no POST)
- `action_gated` — preferred production profile for Splunk notable writeback idempotency (`notable_rest`), approval-gated ServiceNow create, and DynamoDB side-effect idempotency

Default deploy posture: `CAPABILITY_PROFILES=core` with `SplunkSinkMode=s3`.

### Shipped on `main` (Wave 2, optional)

- `analyst_portal` — S3 case archive, DynamoDB CaseIndex, post-archive embedding,
  read-only portal API Lambda, static React SPA, and pinned-case Q&A

Stack-managed when enabled: regional API Gateway HTTP API and an optional
private UI bucket served through the portal Lambda when `PortalUiBucketName` is set. See
[`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).

### Operator-led (not evidenced in repo)

- Real-AWS dev/staging/prod deploy validation for Wave 1 closeout
- Real-AWS Wave 2 portal staging validation
- Per-customer JWT issuer/audience, browser CORS, DNS, WAF, and IdP registration for `analyst_portal`
- Lambda container image build/publish when the org cannot use the repo `Dockerfile` unchanged

## What "Ready" Means

Ready means the organization has settled business, security, platform, and
ownership decisions so an engineer can deploy, test, and hand off without first
resolving major unknowns.

## Executive Readiness Buckets

An organization is broadly ready when it can answer these questions:

1. **Environment**: Target AWS account, region, initial capability profile set, and output sink mode (`s3` vs `notable_rest`)?
2. **Approvals and access**: Platform access, security approval, and policy changes for Bedrock, private OpenSearch, and optional external HTTPS endpoints?
3. **Delivery path**: How the Lambda image is built, published to ECR, and deployed?
4. **Integration inputs**: Upstream input source (SIEM/SOAR), and for each enabled profile, OpenSearch indexes/corpora, endpoints, allowlists, and secret ARNs?
5. **Ownership and support**: Who maintains the application and each optional integration (Splunk, Elasticsearch, ServiceNow)?
6. **Portal front door (Wave 2 only)**: If `analyst_portal` is enabled, what are the JWT issuer/audience, browser CORS origins, SPA upload owner, and approved regional API Gateway hostname/access controls?

If those six buckets are not understood, this is not yet a low-friction deployment.

## Before Engineer-Led Integration Starts

- environment chosen: account, region, initial `CapabilityProfiles` list, sink mode, post-deploy owner
- deployment workstation ready: `AWS CLI`, `SAM CLI`, Docker
- platform access to deploy SAM, publish ECR images, and create required AWS resources
- security, model approval, and policy authority in place for Bedrock and optional integrations
- Lambda image build-and-publish path decided
- integration inputs known: bucket naming, upstream writer, and per-profile secrets, OpenSearch settings, and endpoint mapping
- if external writes are planned, Splunk or ServiceNow owners confirmed write boundaries, approval workflow, and idempotency; new production writeback rollouts should use `action_gated`

## What The Engineer Can Do Once Engaged

- verify prerequisites and deployment tooling
- build or standardize the Lambda image and publish it to ECR
- supply deploy-time parameters (`CapabilityProfiles`, buckets, `EcrRepositoryUri`, `ImageDigest`, `BedrockAnalysisModelId`, `BedrockAnalysisModelArn`, sink mode, optional integration settings) and run the documented SAM path
- validate runtime behavior, logs, and report generation (markdown/JSON/HTML as enabled), optional RAG and read-only investigation, and if enabled Splunk writeback or ServiceNow paths
- if `analyst_portal` is enabled, validate archive write, embed completion, portal API routes, SPA load, and pinned-case chat after customer front-door wiring
- run smoke tests and hand off rerun and rollback steps

## What May Still Depend On The Customer

- security or platform approval for Bedrock, optional OpenSearch retrieval, and optional HTTPS egress to Splunk, MCP, Elasticsearch, or ServiceNow
- IAM or SCP changes if AWS actions are still blocked
- final confirmation of approved runtime targets, names, regions, and capability profile rollout order
- secret creation, rotation, and access review for each enabled integration
- Splunk or Elasticsearch owner confirmation of query allowlists, indexes, and identifier mapping
- ServiceNow owner confirmation of draft vs create boundaries and signed approval workflow
- for `analyst_portal`, identity-platform owner confirmation of JWT issuer/audience, browser CORS origins, and optional custom DNS in front of stack outputs (`PortalBrowserApiBaseUrl`, `PortalUiDistributionDomainName`)
- network or routing changes if standard egress is not the chosen model

## Status Language

- **Ready**: all six readiness buckets are answered for the planned initial profile set (typically `core` + `s3`, plus `analyst_portal` when enabled)
- **Ready with dependencies**: the path is mostly clear, but approvals, secrets, profile-specific settings, or ownership items are still pending
- **Not ready**: major questions remain in environment, approvals, delivery path, integration inputs, or ownership

## Next Document

See [`AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md`](AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md) for the detailed assessment. Profile-specific operator detail is in [`../operations/platform/CAPABILITY_PROFILES.md`](../operations/platform/CAPABILITY_PROFILES.md). Portal deployment detail is in [`../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
