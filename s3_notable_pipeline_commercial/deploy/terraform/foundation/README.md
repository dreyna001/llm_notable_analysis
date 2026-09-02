# Foundation-only Terraform (legacy and separately owned layouts)

This root composes foundation resources only:

- [`../network/`](../network/)
- [`../kms/`](../kms/)
- [`../ecr/`](../ecr/)
- [`../opensearch/`](../opensearch/)

It does not deploy the application. Commercial Path B must use
[`../customer_default/`](../customer_default/) so foundation and application IAM
policies are wired in one full Terraform plan/apply.

Use this root only when Path A/C remains on the legacy SAM application workflow,
or when a customer has explicitly split foundation ownership into separate state.
Those layouts retain their own handoff and policy-update procedures.

## Prerequisites

- Terraform 1.6+ and AWS provider 6.x
- Existing VPC and private subnets
- Customer-approved remote state backend
- Approved commercial AWS account in `us-east-1`
- OpenSearch administrator principal ARNs when enabled
- KMS administrator principal ARNs when a key is created

## Apply

```bash
cd deploy/terraform/foundation
cp terraform.tfvars.example terraform.tfvars
# Edit every placeholder.

terraform fmt -check
terraform init
terraform validate
terraform plan -out foundation.tfplan
terraform show foundation.tfplan
# Apply only after account, role, region, resource, cost, and customer approval.
terraform apply foundation.tfplan
```

## Outputs

```bash
terraform output
terraform output -json
```

For Path A/C SAM parameters, use the `sam_environment` output. Do not use this
output-to-SAM handoff for Path B.

## Destruction

`terraform destroy` is destructive teardown. Confirm all application dependencies
and retained-data requirements, then obtain explicit customer approval before use.
