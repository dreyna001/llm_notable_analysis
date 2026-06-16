# AWS Readiness Assessment

This is the detailed readiness assessment for deploying `s3_notable_pipeline` on AWS (Wave 1).

Use `AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md` as the front-door summary. Use this document when you need the full technical rationale, operational implications, and integration framing.

## What Ready Looks Like

For `s3_notable_pipeline`, readiness means an org can take the package, provide a small number of approved environment-specific values, follow one documented deployment path, and get to a successful end-to-end test without opening code or making AWS design decisions during deployment.

An org is genuinely ready for this package when all of this is already true:

- they have a target AWS account and region chosen for the pipeline
- they know the initial `CapabilityProfiles` list (recommended start: `core` only) and whether they will use `s3` sink mode or later enable `notable_rest`; new production writeback rollouts should use `action_gated`
- they have Bedrock access for the exact model or inference profile the package expects, in the exact region they will deploy to
- if `rag`, `spl_readonly`, or `elastic_readonly` is planned, they have approved Bedrock Knowledge Base IDs and `bedrock:Retrieve` permission for those KBs
- they can create and use ECR, S3, Lambda, IAM, CloudWatch Logs, and CloudFormation/SAM in that AWS account
- if read-only investigation is in scope, Splunk or Elasticsearch owners have approved allowlists, endpoints, and read-only credentials
- if `action_gated` is in scope, they have Splunk REST or ServiceNow credentials with the minimum required scope, plus DynamoDB for side-effect idempotency
- their security team is comfortable with S3 receiving notable files, Lambda reading the input bucket and writing the output bucket, Lambda invoking Bedrock, optional KB retrieve, optional HTTPS to customer SIEM/search/ticketing endpoints, and CloudWatch logging
- their networking model is already decided, whether that is standard internet egress or a private-routing/VPC pattern
- they have an operator who will own runtime understanding, smoke testing, and maintenance after deploy

If those decisions are still undecided, the org is not deployment-ready even if it already has an AWS account.

## Practical Readiness Checklist

### 1. Platform And Access

They need:

- `AWS CLI`, `SAM CLI`, and `Docker` available and working on the deployment workstation (for example, the engineer's laptop, a jump box, a build/deploy VM, or a CI runner)
- permission to deploy CloudFormation/SAM stacks
- permission to create or reference ECR images
- permission to create S3 buckets with globally unique names
- if `action_gated` is enabled, permission to create or reference a DynamoDB idempotency table

This matches the stated fast path in `s3_notable_pipeline/README.md` and `s3_notable_pipeline/setup-and-deploy.ps1`.

### 2. Bedrock Readiness

This is the biggest hidden blocker.

They need:

- Bedrock enabled in the chosen region
- access to the exact model or inference profile the stack will call
- IAM permission for `bedrock:InvokeModel`
- if `rag` or query-grounding profiles are enabled, IAM permission for `bedrock:Retrieve` on the configured Knowledge Bases
- confirmation that org-level controls like SCPs (AWS Organizations guardrails that can deny actions even when IAM allows them) are not blocking the model or KB access

For this package, Bedrock readiness must be explicit, because `s3_notable_pipeline/template-sam.yaml` ties Bedrock to a configurable inference profile ARN. If the customer account, region, or approved model differs from what they deploy, deployment may succeed but runtime will fail.

### 3. Artifact And Packaging Readiness

For low-friction deployment, the org should not have to figure out how to manufacture the runtime artifact.

Right now, the package still assumes they can resolve:

- what base image to build from
- how to publish the Lambda image to ECR
- what `ImageUri` to pass to SAM

SAM expects an `ImageUri` pointing at an image already in ECR. Until that image exists, deploy is blocked. The repo `Dockerfile` uses a placeholder or org-specific base image, so many teams cannot build it unchanged. In practice, "ready to deploy" implicitly requires "we already know how to build and publish this Lambda image."

### 4. Data And Runtime Contract Readiness

The org needs to understand exactly what the pipeline expects and produces.

They should already agree on:

- input arrives as S3 objects under `incoming/`
- one object equals one analysis run
- each object or file can arrive as a `.txt` or a `.json`
- empty objects and placeholders are skipped
- output lands under `reports/` as markdown and JSON; HTML when `html_reports` is enabled
- optional read-only investigation and ServiceNow draft content appear in JSON when those profiles are enabled
- if using `notable_rest`, the filename stem becomes `finding_id` for the Splunk REST update; new production rollouts should pair this with `action_gated`
- if using ServiceNow create, a signed `servicenow_create_approval` object must be present in the incoming payload
- `spl_readonly` and `elastic_readonly` are mutually exclusive per deployment

Those behaviors are defined in `s3_notable_pipeline/README.md`, `docs/operations/CAPABILITY_PROFILES.md`, and `s3_notable_pipeline/lambda_handler.py`. If the customer upstream SOAR or Splunk workflow does not match those assumptions, they will hit blockers even if AWS deployment itself works.

### 5. Capability Profile Readiness

Before enabling optional profiles beyond `core`, the org should have profile-specific inputs ready:

- `html_reports` — no additional secrets; acceptance of a third S3 report artifact.
- `rag` — curated SOC Knowledge Base, `RAG_BEDROCK_KB_ID`, retrieve IAM, advisory-context approval.
- `spl_readonly` — Splunk owner approval, executor choice (`rest` or `mcp`), index/command/field allowlists, secrets, optional SPL grounding KB.
- `elastic_readonly` — Elasticsearch owner approval, HTTPS base URL, API key secret, index allowlist, optional grounding KB.
- `ticket_draft` — ServiceNow assignment group for draft payloads (no POST).
- `action_gated` — write approval, `SIDE_EFFECT_IDEMPOTENCY_TABLE`, Splunk and/or ServiceNow secrets, signed create approval workflow.

Recommended order: `core` + `s3` first, then one profile at a time in non-production. Full operator workflow is in `docs/operations/CAPABILITY_PROFILES.md`.

### 6. Secrets And External Integration Readiness

If they want anything beyond `core` in `s3` mode, they need the external integration prepared before enabling that profile.

For `notable_rest` writeback:

- `SplunkBaseUrl` (template parameter -> runtime `SPLUNK_BASE_URL`)
- `SplunkApiTokenSecretArn` (Secrets Manager ARN pointing to the Splunk REST bearer token)
- optional `SplunkApiTokenSecretField` if the secret is JSON (default `token`)
- agreement that the target endpoint and `finding_id` mapping are correct

For `spl_readonly`:

- Splunk REST or MCP endpoint and auth secret ARN
- approved search allowlists and timeouts

For `elastic_readonly`:

- `ELASTICSEARCH_BASE_URL` (HTTPS when execution is enabled)
- `ELASTICSEARCH_API_KEY_SECRET_ARN` and index allowlist

For ServiceNow (`ticket_draft` or `action_gated` create):

- `SERVICENOW_BASE_URL`, token secret, and for create, `SERVICENOW_APPROVAL_HMAC_SECRET_ARN`
- documented signed approval workflow (`docs/operations/SERVICENOW_OPERATIONS.md`)

If they do not already know where these secrets live, who manages them, and how they will be injected into runtime, they are not ready for that profile.

### 7. Operational Readiness

A low-issue deployment also requires basic day-2 readiness:

- someone knows where Lambda logs are
- someone can rerun the smoke test for each enabled profile
- someone can upload a known-good test file
- someone can tell the difference between deploy failure, Bedrock permission failure, KB retrieve failure, query policy rejection, and sink integration failure
- there is a rollback path to the last known-good image
- if `action_gated` is enabled, someone understands idempotency keys and duplicate side-effect behavior

Without this, deployment might succeed but the org will still feel blocked.

## The Real "Green State"

For `s3_notable_pipeline`, an org is in true green status when it can answer these questions immediately:

1. What AWS account and region is this going to?
2. What exact Bedrock model or inference profile is approved there?
3. Do we have `bedrock:InvokeModel` permission for that target?
4. What is the ECR image URI for this release?
5. What are the globally unique input and output bucket names?
6. What `CapabilityProfiles` are enabled for this release?
7. Are we using `s3` or `notable_rest` sink mode, and are new production writes using `action_gated`?
8. For each enabled profile, where do Knowledge Base IDs, secrets, allowlists, and endpoints come from?
9. What upstream system is writing files into `incoming/`?
10. Does that upstream system match the filename, payload, and ServiceNow approval assumptions?
11. Who owns smoke testing and runtime support after deploy?

If they cannot answer those without a workshop, they are not ready for low-friction deployment.

## How To Think About Engineer-Led Integration

This section does not add new requirements. It reorganizes the same readiness points above into three buckets: what must already be true before engineer-led work starts, what an engineer can execute once access is available, and what may still require customer or external-team action during the work.

### 1. What Must Be True Before Engineer-Led Integration Starts

- the target AWS account and region are chosen
- the org knows the initial `CapabilityProfiles` list and sink mode
- `AWS CLI`, `SAM CLI`, and `Docker` are available and working on the deployment workstation
- the deployment team has permission to deploy CloudFormation/SAM stacks, create or reference ECR images, and create globally unique S3 buckets
- Bedrock is enabled in the chosen region and the exact model or inference profile is approved
- there is `bedrock:InvokeModel` permission for that target; `bedrock:Retrieve` if RAG or grounding profiles are planned
- the org has already decided how the Lambda image will be built and published to ECR
- for each planned optional profile, the team knows required KB IDs, secrets, allowlists, and owner approvals
- if `action_gated` is in scope, idempotency table and write approval boundaries are understood
- the upstream system that writes notable files into `incoming/` is identified and assumptions are understood
- someone is identified to own smoke testing and runtime support after deploy

### 2. What An Engineer Can Do Once Access Is Available

- verify local prerequisites and deploy-path tooling
- build or standardize the Lambda image and publish it to ECR
- supply deploy-time parameters such as account ID, bucket names, `CapabilityProfiles`, sink mode, image URI, and profile-specific settings
- deploy the stack through the documented SAM path
- validate that the deployed Bedrock target, region, and runtime settings match the approved values
- run smoke tests by uploading a known-good file and checking output for each enabled profile
- verify Lambda logs, report generation (markdown/JSON/HTML), optional RAG and read-only investigation, and if enabled writeback or ServiceNow paths
- distinguish whether a failure is coming from deployment, Bedrock invocation, KB retrieve, query policy, or sink integration
- document or hand off the exact values and commands needed for rerun and rollback

### 3. What May Still Require Customer Or External-Team Action During Integration

- security or platform approval for S3, Lambda, Bedrock, optional KB retrieve, optional HTTPS egress, and CloudWatch use
- IAM changes or SCP exceptions if Bedrock or other AWS actions are still blocked
- confirmation that the selected model or inference profile and Knowledge Bases are approved for that account and region
- final approval of globally unique bucket names and target deployment region
- secret creation, rotation, and access review for each enabled integration
- Splunk or Elasticsearch owner confirmation of allowlists and endpoint mapping
- ServiceNow owner confirmation of draft vs create boundaries and signed approval workflow
- network or private-routing changes if standard internet egress is not the chosen model

## Current Package Friction

For `s3_notable_pipeline` specifically, these are the main sources of deployment friction today:

- `s3_notable_pipeline/template-sam.yaml` and `template-cfn.yaml` parameterize account ID, but customers must still align the selected model/profile, region, and optional profile settings with approvals
- `s3_notable_pipeline/Dockerfile` uses a placeholder or private-style base image, so many orgs cannot build it unchanged
- `s3_notable_pipeline/setup-and-deploy.ps1` checks for either Nova models or Claude Sonnet 4.6 inference profiles, but operators still need to verify the exact deploy-time model/profile and region match template and runtime settings
- optional profiles add integration surface area (Knowledge Bases, Splunk/MCP, Elasticsearch, ServiceNow, DynamoDB); each requires owner approval and secrets before enablement
- Splunk integration has a template-driven `notable_rest` path; new production rollouts should pair it with `action_gated`, and operators still need an approved secret lifecycle and write approval boundaries

## Security And Scope Boundaries (Wave 1)

These boundaries are intentional and should be reflected in customer security review:

- RAG and query-grounding snippets are **advisory**; observed case facts come from the ingested notable.
- Splunk SPL and Elasticsearch DSL are **generated, policy-validated, and read-only** when investigation profiles are enabled.
- **No autonomous remediation**, suppression, or case closure.
- New production external writes (Splunk notable comments, ServiceNow creates) should use **`action_gated`**, explicit configuration, signed ServiceNow approval for creates, and **DynamoDB side-effect idempotency**. Legacy `notable_rest` writeback remains supported for existing deployments.
- S3 report writes are not deduplicated by idempotency; customers should treat the object key as the natural boundary for one analysis run.

See `docs/security/ATTACK_LLM_ANALYSIS.md` and `docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md` for grounding and flow detail.
