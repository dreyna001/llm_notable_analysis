# ECR Terraform

Standalone Terraform for the legacy commercial AWS Paths A/C Lambda container
repository. It creates one ECR repository with scan-on-push enabled and an
optional lifecycle policy. It does not build, tag, push, or deploy images.

Path B uses the ECR bootstrap mode in [`../customer_default/`](../customer_default/).
Use this standalone module only for an explicitly split foundation state or
legacy Paths A/C.
Image build and push runbook:
[`../../docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](../../docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md).

## Prerequisites

- Terraform 1.6+
- AWS provider 6.x
- Approved commercial AWS account and deployment role
- Region `us-east-1`
- Remote Terraform state configured according to customer policy
- Explicit customer approval before `terraform apply`

## State

No backend block is committed because backend ownership, bucket names, lock
strategy, and KMS policy are customer-specific. Configure an approved remote
backend before production use. Do not use local state for production.

## Create the repository

```bash
cd deploy/terraform/ecr
cp terraform.tfvars.example terraform.tfvars
# Edit every placeholder.

terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out ecr.tfplan
terraform show ecr.tfplan
# Approval gate: account, role, us-east-1, resources, and customer approval.
terraform apply ecr.tfplan
```

Copy outputs to the legacy Paths A/C SAM parameter source:

```bash
terraform output ecr_repository_uri
terraform output ecr_repository_arn
terraform output sam_environment
```

## Image tags and digest-pinned deploy

This module allows mutable tags (`image_tag_mutability = "MUTABLE"`) so release
engineering can reuse a tag such as a Git SHA during iterative pushes. SAM and
CloudFormation still require digest-pinned deploy:

- Set `ECR_REPOSITORY_URI` to the repository URI without tag or digest.
- Set `ImageDigest` to the immutable `sha256:...` value from ECR after push.
- Do not deploy with `latest` or a floating tag reference.

Build, authenticate, push, and capture the digest per
[`DEPLOYMENT_IMAGE_STEPS.md`](../../docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md).

## Lifecycle policy

Default:

```hcl
enable_lifecycle_policy = true
lifecycle_image_count   = 30
```

Disable retention management:

```hcl
enable_lifecycle_policy = false
```

## Validation

```bash
aws ecr describe-repositories \
  --repository-names "$(terraform output -raw repository_name)" \
  --region us-east-1 \
  --query 'repositories[0].{Name:repositoryName,Uri:repositoryUri,ScanOnPush:imageScanningConfiguration.scanOnPush,Mutability:imageTagMutability}' \
  --output table
```

Pass criteria:

- Repository URI matches `ecr_repository_uri`
- `ScanOnPush=true`
- `Mutability=MUTABLE`
- Lifecycle policy present when enabled
- Active account, partition `aws`, and region `us-east-1`

## Destruction

`terraform destroy` deletes the repository. Images become unavailable to Lambda
deployments that reference them. Require explicit customer approval, confirm no
active stack still references the repository digest, and validate the exact
workspace and repository name first.
