# OpenSearch Terraform

Customer-owned Terraform for the commercial AWS Path B VPC-only OpenSearch
domain. It creates the domain, a dedicated domain security group, and HTTPS
ingress from existing Lambda security groups. It does not create the customer
VPC, subnets, Lambda security groups, NAT gateways, VPC endpoints, KMS keys, or
application indexes.

## Prerequisites

- Terraform 1.6+
- AWS provider 6.x
- Approved commercial AWS account and deployment role
- Region `us-east-1`
- Existing VPC, private subnets, and Lambda security group
- Remote Terraform state configured according to customer policy
- Explicit customer approval before `terraform apply`

## State

No backend block is committed because backend ownership, bucket names, lock
strategy, and KMS policy are customer-specific. Configure an approved remote
backend before production use. Do not use local state for production.

## Phase A — create the domain

```bash
cd deploy/terraform/opensearch
cp terraform.tfvars.example terraform.tfvars
# Edit every placeholder. Keep read_role_arns and write_role_arns empty.

terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out opensearch.tfplan
terraform show opensearch.tfplan
# Approval gate: account, role, us-east-1, resources, cost, and customer approval.
terraform apply opensearch.tfplan
```

Copy outputs to `customer-default.env`:

```bash
terraform output opensearch_endpoint
terraform output opensearch_domain_arn
terraform output opensearch_security_group_id
terraform output sam_environment
```

The application creates `soc_knowledge`, `splunk_dictionary`, and `case_chunks`
on first write; Terraform does not create application index mappings.

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
read_role_arns = [
  "arn:aws:iam::<account-id>:role/<physical-NotableAnalyzerFunctionRole>",
  "arn:aws:iam::<account-id>:role/<physical-PortalApiFunctionRole>",
]

write_role_arns = [
  "arn:aws:iam::<account-id>:role/<physical-CaseEmbedFunctionRole>",
  "arn:aws:iam::<account-id>:role/<physical-RagIngestionFunctionRole>",
]
```

Review and apply only the access-policy change:

```bash
terraform plan -out opensearch-phase-b.tfplan
terraform show opensearch-phase-b.tfplan
# Approval gate.
terraform apply opensearch-phase-b.tfplan
```

## CMK

Default:

```hcl
kms_key_arn = null
```

Customer-managed key:

```hcl
kms_key_arn = "arn:aws:kms:us-east-1:<account-id>:key/<key-id>"
```

Create and authorize the CMK before creating the domain. Changing the domain's
at-rest encryption key later is not treated as a routine in-place operation.

## Validation

```bash
aws opensearch describe-domain \
  --domain-name "$(terraform output -raw domain_name)" \
  --region us-east-1 \
  --query 'DomainStatus.{Created:Created,Processing:Processing,Endpoint:Endpoint,Arn:ARN}' \
  --output table
```

Pass criteria:

- `Created=true`, `Processing=false`
- VPC endpoint only
- HTTPS and TLS 1.2 enforced
- At-rest and node-to-node encryption enabled
- One private subnet per selected Availability Zone
- OpenSearch security group permits TCP 443 from Lambda security groups only
- No `403` from product Lambdas after Phase B

## Destruction

`terraform destroy` deletes the domain and its indexes. Treat destruction as
irreversible data loss. Require explicit customer approval, validate snapshots
and retention requirements, and confirm the exact workspace and domain first.
