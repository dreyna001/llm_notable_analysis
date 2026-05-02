# AWS Readiness Assessment

This is the detailed readiness assessment for deploying `s3_notable_pipeline` on AWS.

Use `AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md` as the front-door summary. Use this document when you need the full technical rationale, operational implications, and integration framing.

## What Ready Looks Like
For `s3_notable_pipeline`, readiness means an org can take the package, provide a small number of approved environment-specific values, follow one documented deployment path, and get to a successful end-to-end test without opening code or making AWS design decisions during deployment.

An org is genuinely ready for this package when all of this is already true:

- they have a target AWS account and region chosen for the pipeline
- they know whether they are using only `s3` mode, or integrating with Splunk via `notable_rest`
- they have Bedrock access for the exact model or inference profile the package expects, in the exact region they will deploy to
- they can create and use ECR, S3, Lambda, IAM, CloudWatch Logs, and CloudFormation/SAM in that AWS account
- if Splunk is in scope, they have a Splunk REST API token that has read and write access to notables
- their security team is already comfortable with S3 receiving notable files, Lambda reading the input bucket and writing the output bucket, Lambda invoking Bedrock, and CloudWatch logging
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

This matches the stated fast path in `s3_notable_pipeline/README.md` and `s3_notable_pipeline/setup-and-deploy.ps1`.

### 2. Bedrock Readiness
This is the biggest hidden blocker.

They need:

- Bedrock enabled in the chosen region
- access to the exact model or inference profile the stack will call
- IAM permission for `bedrock:InvokeModel`
- confirmation that org-level controls like SCPs (AWS Organizations guardrails that can deny actions even when IAM allows them) are not blocking the model

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
- output in `s3` and `notable_rest` modes lands under `reports/`
- if using `notable_rest`, the filename stem becomes `finding_id` for the Splunk REST update

Those behaviors are defined in `s3_notable_pipeline/README.md` and `s3_notable_pipeline/lambda_handler.py`. If the customer upstream SOAR or Splunk workflow does not match those assumptions, they will hit blockers even if AWS deployment itself works.

### 5. Secrets And External Integration Readiness
If they want anything beyond `s3` test mode, they need the external integration prepared before deployment.

For `notable_rest` mode:

- `SplunkBaseUrl` (template parameter -> runtime `SPLUNK_BASE_URL`)
- `SplunkApiTokenSecretArn` (Secrets Manager ARN pointing to the same Splunk REST bearer token you would otherwise place in `SPLUNK_API_TOKEN`; Lambda reads it at runtime)
- optional `SplunkApiTokenSecretField` if the secret is JSON (default `token`)
- agreement that the target endpoint and `finding_id` mapping are correct

If they do not already know where these secrets live, who manages them, and how they will be injected into runtime, they are not ready.

### 6. Operational Readiness
A low-issue deployment also requires basic day-2 readiness:

- someone knows where Lambda logs are
- someone can rerun the smoke test
- someone can upload a known-good test file
- someone can tell the difference between deploy failure, Bedrock permission failure, and sink integration failure
- there is a rollback path to the last known-good image

Without this, deployment might succeed but the org will still feel blocked.

## The Real "Green State"
For `s3_notable_pipeline`, an org is in true green status when it can answer these questions immediately:

1. What AWS account and region is this going to?
2. What exact Bedrock model or inference profile is approved there?
3. Do we have `bedrock:InvokeModel` permission for that target?
4. What is the ECR image URI for this release?
5. What are the globally unique input and output bucket names?
6. Are we using `s3` or `notable_rest` sink mode?
7. If Splunk is involved, where do the required secrets come from?
8. What upstream system is writing files into `incoming/`?
9. Does that upstream system match the filename and payload assumptions?
10. Who owns smoke testing and runtime support after deploy?

If they cannot answer those without a workshop, they are not ready for low-friction deployment.

## How To Think About Engineer-Led Integration
This section does not add new requirements. It reorganizes the same readiness points above into three buckets: what must already be true before engineer-led work starts, what an engineer can execute once access is available, and what may still require customer or external-team action during the work.

### 1. What Must Be True Before Engineer-Led Integration Starts
- the target AWS account and region are chosen
- the org knows whether it is using `s3` or `notable_rest`
- `AWS CLI`, `SAM CLI`, and `Docker` are available and working on the deployment workstation
- the deployment team has permission to deploy CloudFormation/SAM stacks, create or reference ECR images, and create globally unique S3 buckets
- Bedrock is enabled in the chosen region and the exact model or inference profile is approved
- there is `bedrock:InvokeModel` permission for that target
- the org has already decided how the Lambda image will be built and published to ECR: engineer workstation build/push, jump box or admin VM build/push, CI pipeline build/push, or customer-owned central build platform
- if `notable_rest` is in scope, the team already knows where `SplunkBaseUrl` and `SplunkApiTokenSecretArn` will come from
- the upstream system that writes notable files into `incoming/` is identified and the filename and payload assumptions are understood
- someone is identified to own smoke testing and runtime support after deploy

### 2. What An Engineer Can Do Once Access Is Available
- verify local prerequisites and deploy-path tooling
- build or standardize the Lambda image and publish it to ECR
- supply deploy-time parameters such as account ID, bucket names, sink mode, image URI, and notable_rest settings
- deploy the stack through the documented SAM path
- validate that the deployed Bedrock target, region, and runtime settings match the approved values
- run the smoke test by uploading a known-good file and checking output behavior
- verify Lambda logs, output report generation, and if enabled the notable_rest writeback path
- distinguish whether a failure is coming from deployment, Bedrock invocation, or the sink integration
- document or hand off the exact values and commands needed for rerun and rollback

### 3. What May Still Require Customer Or External-Team Action During Integration
- security or platform approval for S3, Lambda, Bedrock, and CloudWatch use
- IAM changes or SCP (AWS Organizations Service Control Policy) exceptions if Bedrock or other AWS actions are still blocked
- confirmation that the selected model or inference profile is the approved one for that account and region
- final approval of globally unique bucket names and target deployment region
- secret creation, rotation, and access review for `SplunkApiTokenSecretArn`
- confirmation from the Splunk owner that the endpoint path and `finding_id` mapping are correct
- network or private-routing changes if standard internet egress is not the chosen model

## Current Package Friction
For `s3_notable_pipeline` specifically, these are the main sources of deployment friction today:

- `s3_notable_pipeline/template-sam.yaml` and `template-cfn.yaml` parameterize account ID, but customers must still align the selected model/profile and region with approvals
- `s3_notable_pipeline/Dockerfile` uses a placeholder or private-style base image, so many orgs cannot build it unchanged
- `s3_notable_pipeline/setup-and-deploy.ps1` checks for either Nova models or Claude Sonnet 4.5 inference profiles, but operators still need to verify the exact deploy-time model/profile and region match template and runtime settings
- Splunk integration now has a template-driven notable_rest injection path, but operators still need an approved secret lifecycle for `SplunkApiTokenSecretArn`

