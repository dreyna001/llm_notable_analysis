# AWS Readiness Overview

Executive gateway for the AWS deployment path of `s3_notable_pipeline`. Use this document to decide whether engineer-led deployment can begin. Use `AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md` for the detailed technical rationale.

## In Scope
AWS deployment of `s3_notable_pipeline` through SAM / CloudFormation, using Bedrock for analysis and `s3` or `notable_rest` for output.

## What "Ready" Means
Ready means the organization has already settled the key business, security, platform, and ownership decisions so an engineer can deploy, test, and hand off the package without first resolving major unknowns.

## Executive Readiness Buckets
An organization is broadly ready when it can answer these five questions:

1. **Environment**: Do we know the target AWS account, region, and output sink mode (S3 or Splunk ES)?
2. **Approvals and access**: Do we have the required platform access, security approval, and ability to make or obtain needed policy changes?
3. **Delivery path**: Do we know how the Lambda image will be built, published to ECR, and deployed?
4. **Integration inputs**: Do we know the upstream input source (SIEM), and for that upstream input source, where the endpoint and API keys come from?
5. **Ownership and support**: Do we know who owns maintaining the application?

If those five buckets are not already understood, this is not yet a low-friction deployment.

## Before Engineer-Led Integration Starts
- environment is chosen: account, region, sink mode, and post-deploy owner
- deployment workstation and toolchain are ready
- the team has the platform access needed to deploy, publish images, and create required AWS resources
- security, model approval, and policy authority are in place so the package can actually run once deployed
- the Lambda image build-and-publish path to ECR is already decided
- integration inputs are known: bucket naming, upstream writer, and if Splunk is used, secret source and endpoint mapping

## What The Engineer Can Do Once Engaged
- verify prerequisites and deployment tooling
- build or standardize the Lambda image and publish it to ECR
- provide deploy-time parameters and execute the documented SAM deployment path
- validate runtime behavior, logs, output generation, and if enabled the Splunk writeback path
- run the smoke test and hand off rerun and rollback steps

## What May Still Depend On The Customer
- final security or platform approval
- policy changes or exceptions if AWS actions are still blocked
- final confirmation of approved runtime targets, names, and regions
- secret creation, rotation, and access review
- confirmation from the Splunk owner that endpoint and identifier mapping are correct
- network or routing changes if standard egress is not the chosen model

## Status Language
- `Ready`: all five readiness buckets are already answered
- `Ready with dependencies`: the path is mostly clear, but one or more approvals, secrets, or ownership items are still pending
- `Not ready`: major questions remain in environment, approvals, delivery path, integration inputs, or ownership

## Next Document
See `AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md` for the detailed assessment.
