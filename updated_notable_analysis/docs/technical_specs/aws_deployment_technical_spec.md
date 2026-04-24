# AWS Deployment Technical Spec

## Status

This document is the normative implementation contract for the current AWS wrapper slice of Diff 4.

If wording conflicts with planning notes, this spec wins for the AWS implementation block.

## 1. Purpose

Define the smallest production-shaped AWS wrapper around shared `updated_notable_analysis/core`.

This slice exists to establish deterministic AWS runtime wiring without changing shared business logic or cutting over legacy runtime paths.

## 2. Scope

### In scope

- create first `updated_notable_analysis/aws/` package
- provide Lambda handler entrypoint
- support direct event and S3-triggered payload intake
- load and validate normalized alert payloads
- invoke a shared-core runner seam
- serialize canonical `AnalysisReport` output
- write report JSON to configured S3 destination
- add deterministic tests for wrapper behavior

### Out of scope

- implementing actual core analysis orchestration inside AWS module
- implementing Splunk MCP or Splunk REST adapters
- wiring ServiceNow adapter logic into the AWS runtime path
- implementing on-prem runtime wrappers
- replacing or migrating existing runtime paths

## 3. Baseline Assumptions

- first AWS runtime shape is Lambda container image
- image deployment path uses ECR + SAM/CloudFormation `ImageUri`
- AWS default report sink is S3
- wrapper should fail closed on missing config or unsupported event shape
- shared core remains the source of canonical model and policy semantics

## 4. Required Package and File Shape

Minimum required implementation files:

- `updated_notable_analysis/aws/__init__.py`
- `updated_notable_analysis/aws/config.py`
- `updated_notable_analysis/aws/s3_io.py`
- `updated_notable_analysis/aws/handler.py`
- `updated_notable_analysis/aws/config.env.example`

Minimum required test file:

- `updated_notable_analysis/tests/test_aws_handler.py`

## 5. Runtime Config Contract

### 5.1 Required env vars

- `UPDATED_NOTABLE_AWS_REPORT_OUTPUT_BUCKET`

### 5.2 Optional env vars

- `UPDATED_NOTABLE_AWS_REPORT_OUTPUT_PREFIX` (default `updated-notable-analysis/reports`)
- `UPDATED_NOTABLE_AWS_DEFAULT_PROFILE_NAME`
- `UPDATED_NOTABLE_AWS_DEFAULT_CUSTOMER_BUNDLE_NAME`

### 5.3 Config validation rules

- required bucket must be present and non-empty
- output prefix must be non-empty after normalization
- optional profile and bundle values must be strings when present

## 6. Lambda Event Contract

### 6.1 Direct invoke mode

Event must include:

- `normalized_alert` mapping compatible with `NormalizedAlert` constructor

Optional event overrides:

- `profile_name`
- `customer_bundle_name`

### 6.2 S3 trigger mode

Event must include:

- `Records[0].s3.bucket.name`
- `Records[0].s3.object.key` (URL-encoded keys supported)

Referenced object JSON must contain either:

- `normalized_alert` mapping, or
- direct top-level `NormalizedAlert` mapping

### 6.3 Invalid event handling

The handler must raise deterministic `ValueError` when:

- neither direct payload nor S3 trigger shape is present
- required S3 fields are missing
- payload is not a JSON object mapping

## 7. Core Runner Seam Contract

The AWS wrapper must invoke a deployment-injected runner implementing:

- input: `NormalizedAlert`
- optional runtime selections: `profile_name`, `customer_bundle_name`
- output: canonical `AnalysisReport`

The default runtime path must fail closed until a real core runner is explicitly injected.

## 8. S3 Transport Contract

The AWS wrapper uses one JSON transport seam:

- `get_json_object(bucket, key) -> Mapping[str, Any]`
- `put_json_object(bucket, key, payload) -> None`

Provide:

- boto3-backed default transport
- deterministic in-memory test doubles in unit tests

## 9. Output Contract

Handler successful response must include:

- `status` (`ok`)
- `output_bucket`
- `output_key`
- `source_record_ref`
- `input_ref`

Report object key format:

- `<prefix>/<utc_timestamp>_<sanitized_source_record_ref>.json`

Serialization requirements:

- dataclasses converted to JSON mappings
- enum values serialized by `.value`
- datetimes serialized as UTC ISO-8601 with `Z`

## 10. Test Requirements

Tests must be deterministic and require no live network or AWS account.

Required coverage:

- direct payload invoke path
- S3-triggered payload path
- invalid event denial path
- output key normalization behavior
- env config missing required bucket failure

## 11. Acceptance Criteria

This AWS slice is complete when:

- AWS package exists with thin wrapper modules and config example
- Lambda wrapper accepts direct and S3-triggered alert inputs
- wrapper invokes injected core runner and writes report JSON to S3 transport seam
- missing config and malformed event inputs fail fast
- deterministic tests cover happy and representative failure paths
- no deployment-specific behavior leaks into shared `core` contracts

## 12. Rollback Note

This slice is additive. Existing runtime paths are not modified.

Rollback is straightforward by ignoring or removing the new `updated_notable_analysis/aws` package.

## 13. One-Line Summary

Diff 4 AWS establishes a thin Lambda-image wrapper with explicit env and event contracts that ingests normalized alerts, calls a deployment-injected shared-core runner, and writes canonical report JSON to S3 with deterministic validation and tests.
