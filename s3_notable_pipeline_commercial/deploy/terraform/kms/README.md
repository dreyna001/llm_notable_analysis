# KMS Terraform

Standalone Terraform for legacy commercial AWS Paths A/C optional customer-managed
KMS key (CMK). It creates the key, alias, and key policy for key administrators,
OpenSearch domain encryption, and Phase B Lambda roles. It does not create the
SAM stack, OpenSearch domain, or application resources.

Path B does not use this standalone workflow; it uses
[`../customer_default/`](../customer_default/) and wires role policies in one apply.
The two-phase instructions below apply only to split-state Paths A/C.
Operator runbook: [`../../docs/operations/deployment/KMS_CUSTOMER_KEY.md`](../../docs/operations/deployment/KMS_CUSTOMER_KEY.md).

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

## Phase A — create the key

```bash
cd deploy/terraform/kms
cp terraform.tfvars.example terraform.tfvars
# Edit every placeholder. Keep lambda_role_arns empty.

terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out kms.tfplan
terraform show kms.tfplan
# Approval gate: account, role, us-east-1, resources, cost, and customer approval.
terraform apply kms.tfplan
```

Copy outputs to the legacy Paths A/C SAM parameter source:

```bash
terraform output kms_key_arn
terraform output kms_key_id
terraform output sam_environment
```

Use the key ARN for:

- the legacy SAM `CustomerKmsKeyArn` parameter
- `kms_key_arn` in the OpenSearch Terraform module when the domain encrypts with this CMK

Create the CMK **before** the OpenSearch domain when the domain uses customer-managed
encryption. Changing the domain's at-rest encryption key later is not treated as a
routine in-place operation.

## Phase B — add deployed Lambda roles

After the first SAM deploy, find physical role names:

```bash
aws cloudformation describe-stack-resources \
  --stack-name notable-analyzer-stack \
  --region us-east-1 \
  --query "StackResources[?ResourceType=='AWS::IAM::Role'].[LogicalResourceId,PhysicalResourceId]" \
  --output table
```

Add physical role ARNs to `terraform.tfvars`:

```hcl
lambda_role_arns = [
  "arn:aws:iam::<account-id>:role/<physical-NotableAnalyzerFunctionRole>",
  "arn:aws:iam::<account-id>:role/<physical-CaseEmbedFunctionRole>",
  "arn:aws:iam::<account-id>:role/<physical-RagIngestionFunctionRole>",
  "arn:aws:iam::<account-id>:role/<physical-PortalApiFunctionRole>",
]
```

Include only Lambda roles that exist for your enabled capabilities.

Review and apply only the key-policy change:

```bash
terraform plan -out kms-phase-b.tfplan
terraform show kms-phase-b.tfplan
# Approval gate.
terraform apply kms-phase-b.tfplan
```

## Key policy structure

| Sid | Principal | Actions | When |
| --- | --- | --- | --- |
| `AllowKeyAdministration` | `admin_principal_arns` | `kms:*` | Always |
| `AllowOpenSearchService` | `es.amazonaws.com` | `kms:CreateGrant`, `kms:Decrypt`, `kms:DescribeKey` | `enable_opensearch_grant = true`; `kms:ViaService = es.us-east-1.amazonaws.com` |
| `AllowProductLambdaUse` | `lambda_role_arns` | `kms:Decrypt`, `kms:DescribeKey`, `kms:GenerateDataKey` | Phase B when `lambda_role_arns` is non-empty |

## Validation

```bash
aws kms describe-key \
  --key-id "$(terraform output -raw kms_key_id)" \
  --region us-east-1 \
  --query 'KeyMetadata.{KeyId:KeyId,Enabled:Enabled,KeyRotationEnabled:KeyRotationEnabled,KeyState:KeyState}' \
  --output table
```

Pass criteria:

- Key state `Enabled`
- Rotation matches `enable_key_rotation`
- OpenSearch domain reports encryption at rest with this CMK when aligned
- Test notable processing succeeds after Phase B (no `KMS.AccessDeniedException` in logs)

## Destruction

`terraform destroy` schedules key deletion after the configured waiting period.
Treat destruction as irreversible for encrypted data. Require explicit customer
approval, validate retention requirements, and confirm the exact workspace and
key alias first.
