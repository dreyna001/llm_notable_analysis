# AWS Readiness Overview

Executive gateway for the AWS deployment path of `s3_notable_pipeline` (Wave 1
and optional Wave 2). Use this document to decide whether engineer-led deployment
can begin. Use `AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md` for the
detailed technical rationale.

## In Scope

AWS deployment of `s3_notable_pipeline` through SAM / CloudFormation, using Bedrock
for analysis, S3 for report output, and optional capability profiles.

**Wave 1 profiles:**

- `core` — S3 ingest, Bedrock analysis, markdown + JSON reports (always included)
- `html_reports` — static HTML reports in S3
- `rag` — advisory SOC context from a Bedrock Knowledge Base
- `spl_readonly` — generated SPL and bounded read-only Splunk REST or MCP investigation
- `elastic_readonly` — generated Query DSL and bounded read-only Elasticsearch `_search`
- `ticket_draft` — ServiceNow incident drafts in JSON reports (no POST)
- `action_gated` — preferred production profile for Splunk notable writeback idempotency (`notable_rest`), approval-gated ServiceNow create, and DynamoDB side-effect idempotency

**Wave 2 profile (code-complete on `main`; real-AWS validation still operator-led):**

- `analyst_portal` — S3 case archive, DynamoDB CaseIndex, post-archive embedding,
  read-only portal API Lambda, static React SPA, and pinned-case Q&A with citation
  enforcement

Wave 2 adds stack-managed API Gateway and optional Lambda Function URL outputs.
Customer-specific DNS, WAF, and IdP registration remain operator decisions. See
[`../operations/ANALYST_PORTAL_OPERATIONS.md`](../operations/ANALYST_PORTAL_OPERATIONS.md).
The stack deploys the portal Lambda, HTTP API, optional chat Function URL, and
optional static UI hosting with CloudFront API routing when `PortalUiBucketName`
is set.

## What "Ready" Means

Ready means the organization has already settled the key business, security, platform, and ownership decisions so an engineer can deploy, test, and hand off the package without first resolving major unknowns.

## Executive Readiness Buckets

An organization is broadly ready when it can answer these questions:

1. **Environment**: Do we know the target AWS account, region, initial capability profile set, and output sink mode (`s3` vs `notable_rest`)?
2. **Approvals and access**: Do we have the required platform access, security approval, and ability to make or obtain needed policy changes (Bedrock, optional Knowledge Bases, optional external HTTPS endpoints)?
3. **Delivery path**: Do we know how the Lambda image will be built, published to ECR, and deployed?
4. **Integration inputs**: Do we know the upstream input source (SIEM/SOAR), and for each enabled profile, where endpoints, Knowledge Base IDs, allowlists, and secret ARNs come from?
5. **Ownership and support**: Do we know who owns maintaining the application and each optional integration (Splunk, Elasticsearch, ServiceNow)?
6. **Portal front door (Wave 2 only)**: If `analyst_portal` is enabled, do we know the customer JWT issuer/audience, browser CORS origins, and whether the SPA uses stack CloudFront (`PortalBrowserApiBaseUrl`) or a split API hostname?

If those six buckets are not already understood, this is not yet a low-friction deployment.

## Before Engineer-Led Integration Starts

- environment is chosen: account, region, initial `CapabilityProfiles` list, sink mode, and post-deploy owner
- deployment workstation and toolchain are ready
- the team has the platform access needed to deploy, publish images, and create required AWS resources
- security, model approval, and policy authority are in place so the package can run once deployed
- the Lambda image build-and-publish path to ECR is already decided
- integration inputs are known: bucket naming, upstream writer, and for each optional profile, approved secrets, KB IDs, and endpoint mapping
- if external writes are planned, Splunk or ServiceNow owners have confirmed write boundaries, approval workflow, and idempotency expectations; new production writeback rollouts should use `action_gated`

## What The Engineer Can Do Once Engaged

- verify prerequisites and deployment tooling
- build or standardize the Lambda image and publish it to ECR
- provide deploy-time parameters (`CapabilityProfiles`, buckets, `ImageUri`, sink mode, optional integration settings) and execute the documented SAM deployment path
- validate runtime behavior, logs, report generation (markdown/JSON/HTML as enabled), optional RAG and read-only investigation, and if enabled the Splunk writeback or ServiceNow path
- if `analyst_portal` is enabled, validate archive write, embed completion, portal API routes, SPA load, and cited selected-case chat after customer front-door wiring
- run smoke tests and hand off rerun and rollback steps

## What May Still Depend On The Customer

- final security or platform approval for Bedrock, optional KB retrieve, and optional HTTPS egress to Splunk, MCP, Elasticsearch, or ServiceNow
- policy changes or exceptions if AWS actions are still blocked
- final confirmation of approved runtime targets, names, regions, and capability profile rollout order
- secret creation, rotation, and access review for each enabled integration
- Splunk or Elasticsearch owner confirmation of query allowlists, indexes, and identifier mapping
- ServiceNow owner confirmation of draft vs create boundaries and signed approval workflow
- for `analyst_portal`, identity-platform owner confirmation of JWT issuer/audience, browser CORS origins, and optional custom DNS in front of stack outputs (`PortalBrowserApiBaseUrl`, `PortalUiDistributionDomainName`)
- network or routing changes if standard egress is not the chosen model

## Status Language

- `Ready`: all six readiness buckets are already answered for the planned initial profile set (typically `core` + `s3`, plus `analyst_portal` when enabled)
- `Ready with dependencies`: the path is mostly clear, but one or more approvals, secrets, profile-specific settings, or ownership items are still pending
- `Not ready`: major questions remain in environment, approvals, delivery path, integration inputs, or ownership

## Next Document

See `AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md` for the detailed assessment. Profile-specific operator detail is in `docs/operations/CAPABILITY_PROFILES.md`. Portal deployment detail is in `docs/operations/ANALYST_PORTAL_OPERATIONS.md`.
