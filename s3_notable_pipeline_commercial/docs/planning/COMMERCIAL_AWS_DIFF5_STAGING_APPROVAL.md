# Commercial AWS Diff 5 Staging Approval

## Status

Blocked at the mandatory pre-deployment gate on 2026-08-03. No AWS resource was created, updated, or deleted.

## Verified Evidence

- Target partition and region in the commercial fork: `aws`, `us-east-1`.
- Configured AWS profiles discovered: `default`, `dev0`, and `ai-soc`.
- Each profile is configured for `us-east-1`.
- `sts:GetCallerIdentity` failed for every configured profile with `InvalidClientTokenId`; therefore the AWS account ID, partition, and caller role could not be verified.
- A credential-like plaintext value was detected in the user-level AWS config. Its value is intentionally not recorded here. Treat it as exposed, rotate it, and remove it from the config before deployment.
- Windows SAM CLI 1.150.1 validated both `deploy/aws/template-sam.yaml` and `deploy/aws/template-cfn.yaml` with lint enabled.
- Docker Desktop and LocalStack 4.14 are available; the LocalStack S3, DynamoDB, and Secrets Manager integration flow passed.
- The repository contains no approved `samconfig.toml`, staging account, stack name, ECR repository/digest, unique bucket names, or Bedrock analysis model ARN.
- Current local evidence is green: 276 backend tests passed with LocalStack and 1 opt-in live Bedrock skip; 95 frontend tests and the production build passed.

## Proposed Initial Staging Scope

These are proposed values, not deployment authorization:

| Setting | Proposed value |
| --- | --- |
| Partition | `aws` |
| Region | `us-east-1` |
| Stack | `notable-analyzer-commercial-staging` |
| Capability profiles | `core` |
| Sink mode | `s3` |
| Portal | disabled for the first deployment |
| Account and deployment role/profile | pending verified STS identity and approval |
| Input/output bucket names | pending unique commercial-only names |
| ECR repository and immutable image digest | pending container build and publication |
| Bedrock analysis model ARN | pending customer-approved model access |

The `core` template creates low-volume serverless staging resources: S3, Lambda, SQS, DynamoDB, CloudWatch, IAM, and conditional API resources. A provisional low-volume base-infrastructure envelope is approximately $2–$15 per month, excluding Bedrock inference, stored data, data transfer, and unusual log volume. Bedrock cost cannot be estimated responsibly until the approved model and expected token volume are known.

## Required Unblock Actions

1. Rotate the exposed credential-like value and remove it from the AWS config.
2. Configure a valid short-lived commercial deployment identity, preferably AWS IAM Identity Center or role assumption, for `us-east-1`.
3. Select and approve the commercial profile, account, caller role, stack name, unique bucket names, ECR repository, image digest, and Bedrock model ARN.
4. Re-run `sts:GetCallerIdentity`; report the account ID, partition, caller ARN/profile, region, stack, and intended resources to the user.
5. Obtain explicit user approval for the reported live change before creating the ECR repository, publishing an image, or creating a CloudFormation change set.

## Remaining Diff 5 Validation

After the gate is approved:

- Build and publish the commercial image, then record its immutable ECR digest.
- Create and inspect a CloudFormation change set before execution.
- Deploy `core` only and run the S3 ingestion, SQS/Lambda, Bedrock, report-output, alarms, retry/DLQ, and isolation smoke tests.
- Record the account, role/profile, region, stack, resource identifiers, model, capability profiles, image digest, change-set evidence, test evidence, cost observations, and rollback version.
- Do not mark Diff 5 complete until the live staging acceptance criteria pass.

Rollback applies only to the explicitly approved commercial staging resources. Any destructive cleanup requires separate approval with exact resource identification.
