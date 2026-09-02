# Network Terraform

Standalone Terraform for the legacy commercial AWS Paths A/C VPC network slice. It
creates a product Lambda security group in an existing VPC and optionally
creates gateway or interface VPC endpoints. It does **not** create a VPC,
subnets, NAT gateways, route tables, or OpenSearch resources.

Path B uses [`../customer_default/`](../customer_default/). Use this standalone
module only for an explicitly split foundation state or legacy Paths A/C.
Operator runbook: [`../../docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md`](../../docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md).

## Prerequisites

- Terraform 1.6+
- AWS provider 6.x
- Approved commercial AWS account and deployment role
- Region `us-east-1`
- Existing VPC and private subnets with routes to a NAT gateway **or** planned VPC endpoints
- Remote Terraform state configured according to customer policy
- Explicit customer approval before `terraform apply`

## What this module creates

| Resource | Always? | Notes |
| --- | --- | --- |
| Lambda security group | Yes | Egress TCP 443 to `0.0.0.0/0` for HTTPS via NAT or interface endpoints |
| S3 gateway endpoint | Optional | Associates with route tables for `private_subnet_ids` |
| DynamoDB gateway endpoint | Optional | Same route-table association model as S3 |
| SQS / Logs / Bedrock Runtime / Secrets Manager interface endpoints | Optional | One endpoint per enabled service across `private_subnet_ids` |

The Lambda security group uses broad HTTPS egress so customers can reach AWS APIs
through a NAT gateway. When interface endpoints are enabled, this module also
creates a dedicated endpoint security group that permits HTTPS from the Lambda
security group only.

OpenSearch ingress is configured separately in
[`../opensearch/`](../opensearch/) after you pass the Lambda security group ID
into that module's `lambda_security_group_ids`.

## State

No backend block is committed because backend ownership, bucket names, lock
strategy, and KMS policy are customer-specific. Configure an approved remote
backend before production use. Do not use local state for production.

## Apply workflow

```bash
cd deploy/terraform/network
cp terraform.tfvars.example terraform.tfvars
# Edit every placeholder.

terraform fmt -check -recursive
terraform init
terraform validate
terraform plan -out network.tfplan
terraform show network.tfplan
# Approval gate: account, role, us-east-1, resources, cost, and customer approval.
terraform apply network.tfplan
```

Copy outputs to the legacy Paths A/C SAM parameter source:

```bash
terraform output lambda_security_group_id
terraform output sam_environment
```

Use the same subnet IDs and Lambda security group ID in
[`../opensearch/terraform.tfvars`](../opensearch/terraform.tfvars) before OpenSearch
Phase A.

## NAT gateway vs VPC endpoints

| Approach | Module settings |
| --- | --- |
| **NAT gateway** (default) | Leave all endpoint flags `false`; ensure private subnet route tables send `0.0.0.0/0` to NAT |
| **VPC endpoints** | Enable the gateway and/or interface flags you need; see [`VPC_NETWORK_PREREQUISITES.md`](../../docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md) |

Gateway endpoints (S3, DynamoDB) are free but require route-table association.
Interface endpoints incur hourly and data-processing charges.

## Validation

Before OpenSearch or SAM deploy:

1. `terraform output sam_environment` shows comma-separated subnet IDs with no spaces
2. Lambda security group belongs to the intended VPC
3. Private subnets route HTTPS to NAT **or** required endpoints exist
4. OpenSearch module receives this Lambda security group ID in `lambda_security_group_ids`

After SAM deploy:

1. Lambda functions show `VpcConfig` with your subnets and security group
2. CloudWatch logs show no persistent `Timeout` connecting to OpenSearch or Bedrock

## Destruction

`terraform destroy` removes the Lambda security group and any endpoints created
here. Confirm no running Lambda ENIs or OpenSearch ingress rules still reference
the security group before destroy.
