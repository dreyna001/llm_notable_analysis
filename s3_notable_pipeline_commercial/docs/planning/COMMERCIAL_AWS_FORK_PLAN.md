# Commercial AWS Fork Plan

## Status

- Fork created: complete
- Fork baseline tests: complete
- Commercial AWS implementation: in progress
- Diff 1 commercial deployment boundary: implemented; focused tests pass, SAM lint pending local CLI availability
- Live AWS deployment: not authorized
- Target: commercial AWS partition `aws`, region `us-east-1`

## Goal

Adapt the independent `s3_notable_pipeline_commercial` fork into a production-shaped commercial AWS `us-east-1` product while preserving the copied application architecture, behavior, contracts, and capability-profile system.

This is not a migration or replacement. The existing GovCloud product and its AWS resources remain outside the scope of this work.

## Hard Safety Boundaries

1. Modify files only in `s3_notable_pipeline_commercial/`, except for narrowly required repository-level bookkeeping such as the existing root `.gitignore` exception.
2. Do not edit, import from, symlink to, deploy, delete, or clean up the sibling GovCloud project.
3. Do not add dual-partition behavior. The commercial product must accept only partition `aws` and region `us-east-1`.
4. Do not transfer GovCloud data, secrets, account identifiers, endpoints, model configuration, or runtime state.
5. Do not run live AWS mutations until the commercial account, caller identity, role/profile, region, stack name, and resource names are reported and explicitly approved.
6. Never run a GovCloud deployment or destructive AWS command from this plan.

## Product Invariants

- Preserve S3-to-SQS-to-Lambda processing, retry ownership, DLQs, idempotency, replay behavior, and collision-safe outputs.
- Preserve report schemas, portal APIs, evidence semantics, ATT&CK validation, and operator-visible behavior.
- Preserve DynamoDB, OpenSearch, API Gateway, KMS, CloudWatch, ECR image, and private-networking responsibilities initially.
- Preserve the capability-profile system and enabled-behavior validation.
- Keep internal Python imports under `s3_notable_pipeline`; the outer project and AWS resources identify the commercial product.
- Continue using IAM roles and short-lived credentials. Never introduce static AWS credentials.
- Keep customer-specific values in validated deployment parameters rather than product logic.

## In Scope

- Commercial-only CloudFormation/SAM partition and region guards.
- Commercial ECR, Bedrock, OpenSearch, IAM, KMS, endpoint, and ARN configuration.
- Commercial defaults in runtime configuration, environment examples, and deployment scripts.
- Commercial product naming and operator documentation.
- Tests that prove the deployment rejects non-commercial partitions and regions.
- Local, SAM, container, and approved commercial staging validation.
- A separate pre-production review of the copied frontend dependency advisories.

## Out of Scope

- Any GovCloud code, stack, account, bucket, data, secret, or operational change.
- Data migration, cutover, failover, replication, or cross-partition connectivity.
- Reimplementing the application or replacing the capability-profile system.
- Adopting commercial-only services merely because they are available.
- Dependency upgrades mixed invisibly into partition/region changes.
- Production deployment before staging evidence and explicit approval.

## Required Inputs Before Live AWS Work

- Commercial AWS account ID and approved CLI profile/deployment role.
- Unique commercial stack name and globally unique S3 bucket names.
- Commercial ECR repository and immutable image digest.
- Approved `us-east-1` Bedrock analysis, chat, and embedding model IDs/ARNs.
- Capability profiles and sink mode to mirror from the intended product configuration.
- Commercial VPC, subnet, security-group, private DNS, and routing values.
- Commercial KMS keys, OIDC issuer/audience and analyst grants, CORS origins, retention, quotas, alarms, and external integration secrets/endpoints.
- OpenSearch domain, indexes, capacity, and tenant/deployment identifier when retrieval capabilities are enabled.

## Implementation Diffs

### Diff 1: Lock the commercial deployment boundary

Objective: Make the copied infrastructure commercial-only without changing its resource topology.

Files:

- `deploy/aws/template-sam.yaml`
- `deploy/aws/template-cfn.yaml`
- `tests/test_deploy_templates.py`

Changes:

- Require partition `aws` and region `us-east-1`.
- Replace GovCloud-only ARN patterns, model validation, descriptions, defaults, and rule names.
- Restrict ECR repositories, OpenSearch domains, KMS keys, Secrets Manager secrets, and SNS topics to commercial `us-east-1` where the AWS resource is regional; keep IAM ARNs commercial and regionless.
- Require `OpenSearchRegion=us-east-1` so retrieval cannot silently sign requests for another region.
- Preserve logical resources, conditions, IAM scoping, queues, DLQs, Lambdas, tables, OpenSearch access, portal routes, and alarms.
- Add positive and negative tests for the partition, region, Bedrock ARN, regional resource ARN, ECR URI, and OpenSearch-region constraints.

Verification:

```bash
.venv/bin/python -m pytest tests/test_deploy_templates.py -q -s
sam validate --lint --template-file deploy/aws/template-sam.yaml
```

Acceptance: Both templates are commercial-only and differ from the fork baseline only where the commercial partition or region requires it.

Rollback: Revert only this diff inside the commercial fork; no live resources exist yet.

### Diff 2: Update runtime and deployment-tool defaults

Objective: Remove GovCloud defaults from runtime configuration and operator tooling while preserving behavior.

Files:

- `src/s3_notable_pipeline/config.py`
- `src/s3_notable_pipeline/opensearch_client.py`
- `config.env.example`
- `scripts/setup-and-deploy.sh`
- `scripts/setup-and-deploy.ps1`
- `tests/test_config.py`
- `tests/test_case_archive.py`
- `tests/test_opensearch_rag.py`

Changes:

- Set OpenSearch and AWS fallbacks to `us-east-1`.
- Validate the commercial caller/account/region before build or deployment.
- Pass or enforce `us-east-1` for both guided deployment and saved-configuration deployment paths.
- Update ECR, Bedrock, and deployment guidance to commercial AWS.
- Keep model IDs, accounts, resource names, endpoints, and secrets as required inputs.

Verification:

```bash
.venv/bin/python -m pytest tests/test_config.py tests/test_case_archive.py tests/test_opensearch_rag.py tests/test_deploy_templates.py -q -s
bash -n scripts/setup-and-deploy.sh
```

Acceptance: Local configuration and deployment tooling contain no GovCloud fallback and fail closed on a wrong AWS boundary.

Rollback: Revert only this diff inside the commercial fork.

### Diff 3: Establish independent product identity and documentation

Objective: Make operator-facing material describe only the commercial `us-east-1` product.

Files:

- `README.md`, `docs/README.md`, `docs/architecture/*`
- deployment, security, LLM, RAG, portal, testing, and readiness documentation
- rename `GOVCLOUD_CUSTOMER_CONFIGURATION.md` to `COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`
- rename `AWS_GOVCLOUD_READINESS_PLAN.md` to `AWS_COMMERCIAL_READINESS_PLAN.md`
- rename `AWS_GOVCLOUD_DEFERRED_GAPS.md` to `AWS_COMMERCIAL_DEFERRED_GAPS.md`

Changes:

- Remove GovCloud product assumptions and sibling-project dependencies from operator-facing material.
- Rename GovCloud-specific documents and repair every internal link.
- Convert GovCloud availability statements about Function URLs, CloudFront, Bedrock Knowledge Bases, and S3 Vectors into explicit commercial product decisions or non-goals; do not blindly invert the statements.
- Retain only an internal planning/safety record of the fork origin; runtime and operator contracts must have no GovCloud dependency.
- Document the approved-differences register and customer-set commercial values.

Verification:

```bash
rg -n -i 'govcloud|aws-us-gov|us-gov-' README.md config.env.example deploy scripts src tests docs
```

Acceptance: Any remaining match is explicitly limited to internal safety/history documentation; deployed code, configuration, tests, and operator documentation describe only commercial AWS.

Rollback: Revert only documentation and naming changes in the commercial fork.

### Diff 4: Prove local behavioral parity

Objective: Demonstrate that the commercial boundary changes did not reimplement or regress application behavior.

Files: Tests or fixtures only when a real commercial-boundary gap requires them.

Verification:

```bash
.venv/bin/python -m pytest tests -q -s
npm --prefix frontend/analyst-portal test -- --run
npm --prefix frontend/analyst-portal run build
python -m compileall -q src tests
```

Also run SAM lint, container build/import validation, LocalStack checks where available, and a baseline-to-commercial difference review.

Acceptance:

- Existing backend and frontend suites pass.
- The commercial template validates.
- No application workflow or external contract changed without an approved-difference entry.
- Frontend dependency findings are assessed and remediated or explicitly accepted before production release.

Rollback: Revert the smallest failing diff; do not alter the GovCloud product to make the fork pass.

### Diff 5: Prepare and validate an isolated commercial staging stack

Objective: Deploy only after local evidence and explicit approval, then validate the independent commercial product end to end.

Hard gate before any mutation:

```bash
aws sts get-caller-identity --profile <commercial-profile>
aws configure get region --profile <commercial-profile>
```

The reported account must be the approved commercial account and the region must be `us-east-1`. The stack, buckets, ECR repository, KMS keys, models, VPC resources, secrets, and endpoints must be commercial-only and uniquely named.

Validation:

- Review a CloudFormation change set before execution.
- Deploy the copied capability-profile selection incrementally, beginning with `core` unless the approved commercial configuration says otherwise.
- Run S3 ingestion, SQS/Lambda processing, Bedrock analysis, report output, alarms, retry/DLQ, and enabled-profile smoke tests.
- Record account, region, stack, image digest, models, profiles, resource identifiers, test evidence, and rollback version.

Acceptance: The commercial staging product operates independently in `us-east-1`, and no GovCloud resource or credential appears in the change set, runtime configuration, logs, or evidence.

Rollback: Roll back or remove only the newly approved commercial staging stack. Destructive cleanup requires separate confirmation and exact commercial resource identification.

## Risks and Hard Stops

- Stop if the current deployed capability profiles or model IDs are unknown; do not guess production behavior.
- Stop if a proposed change alters security posture, evidence semantics, external contracts, cost shape, or customer responsibility without approval.
- Stop if credentials resolve to an unexpected account, partition, or region.
- Stop if a commercial service/model difference would require replacing a component; document alternatives and reconcile first.
- Stop before dependency major-version changes or automated audit fixes; handle them as a separate reviewed diff.

## Baseline Evidence

- Forked project files: complete and self-contained.
- Python baseline: `245 passed`, `2 skipped`.
- Frontend baseline: `92 passed`.
- Frontend production build: passed with the existing large-bundle warning.
- Dependency baseline: npm reported three production-tree findings and eight total findings; fixes were not applied during the fork.

## Decision Record

- Keep internal package name `s3_notable_pipeline` for the lowest-friction fork.
- Commercial-only target; no dual-partition implementation.
- Preserve architecture and capability profiles initially.
- Mirror intended capability and sink behavior using independent commercial configuration.
- No GovCloud data or runtime relationship.
- Handle dependency remediation as a separate pre-production gate.
