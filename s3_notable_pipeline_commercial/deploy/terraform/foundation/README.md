# Foundation Terraform (unified Path B stack)

Single root module that composes the commercial Path B foundation modules:

- [`../network/`](../network/) — Lambda security group + optional VPC endpoints
- [`../kms/`](../kms/) — optional customer CMK
- [`../ecr/`](../ecr/) — ECR repository
- [`../opensearch/`](../opensearch/) — OpenSearch domain Phase A

**SAM deploy is not included.** After `terraform apply`, copy outputs into
`customer-default.env` and follow Path B step 7.

Hub doc: [`../README.md`](../README.md). Root README section **3.4** and Path B
section **4**: [`../../../README.md`](../../../README.md).

## When to use foundation vs standalone modules

| Use foundation | Use standalone modules |
| --- | --- |
| One team, one state backend | Separate state per KMS / network / search / ECR |
| Single approval gate for Phase A foundation | Different owners or change windows per slice |
| Greenfield Path B with all flags enabled | Mix Terraform with existing CMK or domain |

## Prerequisites

- Terraform 1.6+, AWS provider 6.x
- Existing **VPC** and **private subnets** (this stack does not create them)
- Remote state configured per customer policy
- `aws_account_id` for the approved commercial account
- `opensearch_admin_principal_arns` when `enable_opensearch=true`
- `kms_admin_principal_arns` when `enable_kms=true`

## Enable flags

| Variable | Default | Creates |
| --- | --- | --- |
| `enable_network` | `true` | Lambda SG + optional endpoints |
| `enable_kms` | `false` | CMK (set `true` when domain encrypts with CMK) |
| `enable_ecr` | `true` | ECR repository |
| `enable_opensearch` | `true` | VPC-only OpenSearch domain |

When a module is disabled, pass existing values:

- `existing_lambda_security_group_ids` when `enable_network=false`
- `existing_kms_key_arn` when `enable_kms=false` and OpenSearch uses a CMK
- `private_subnet_ids` always required when network or OpenSearch is enabled

## Apply workflow

```bash
cd deploy/terraform/foundation
cp terraform.tfvars.example terraform.tfvars
# Edit every placeholder.

terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out foundation.tfplan
terraform show foundation.tfplan
# Approval gate: account, role, us-east-1, resources, cost, customer approval.
terraform apply foundation.tfplan
```

Populate SAM preset:

```bash
terraform output sam_environment
terraform output -json sam_environment
```

Merge into `customer-default.env` at repo root. Complete Bedrock, JWT, and ECR
**image** steps manually, then Path B step 7 (`sam deploy`).

## Phase B (after SAM)

OpenSearch and KMS modules support Phase B by updating `read_role_arns`,
`write_role_arns`, and `kms_lambda_role_arns` with **physical** Lambda role
ARNs from the CloudFormation stack, then re-running `terraform apply` in
foundation or the standalone module.

See [`../../docs/operations/deployment/OPENSEARCH_PROVISIONING.md`](../../docs/operations/deployment/OPENSEARCH_PROVISIONING.md)
and [`../../docs/operations/deployment/KMS_CUSTOMER_KEY.md`](../../docs/operations/deployment/KMS_CUSTOMER_KEY.md).

## Validation

1. `terraform output sam_environment` includes subnet IDs, Lambda SG, OpenSearch
   endpoint/ARN, and ECR URI when modules are enabled
2. OpenSearch domain is VPC-only with HTTPS enforced
3. `customer-default.env` values match Terraform outputs before SAM
4. After SAM, Phase B policies include deployed Lambda role ARNs

## Destruction

`terraform destroy` removes resources created by enabled child modules. Confirm
no Lambda ENIs, OpenSearch ingress, or SAM stack dependencies remain.
