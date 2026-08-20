# Commercial AWS Terraform (customer-owned foundation)

Customer-owned Terraform for Path B **foundation** resources. The product **SAM
stack** (`deploy/aws/template-sam.yaml`) remains the application deploy path —
Terraform does not replace `sam deploy`.

Use Terraform when your organization standardizes on IaC for prerequisites. Use
manual runbooks or the Path B configurator when Terraform is not required.

## What Terraform covers vs what stays manual

| Area | Terraform modules | Still manual / SAM |
| --- | --- | --- |
| Lambda security group + optional VPC endpoints | [`network/`](network/) or [`foundation/`](foundation/) | VPC, subnets, NAT (customer-owned) |
| Customer CMK | [`kms/`](kms/) or foundation | Phase B Lambda role grants after SAM |
| ECR repository | [`ecr/`](ecr/) or foundation | Docker build, push, digest |
| OpenSearch domain (Phase A) | [`opensearch/`](opensearch/) or foundation | Phase B domain policy after SAM |
| Bedrock model access | — | Console / org policy |
| JWT / IdP | — | Customer IdP |
| Analyzer, portal, queues, buckets | — | **SAM deploy (Path B step 7)** |

## Choose a layout

### Option A — Foundation stack (single root)

One state file for network, optional KMS, ECR, and OpenSearch Phase A.

```text
deploy/terraform/foundation/
  terraform init / plan / apply
  terraform output sam_environment   -> customer-default.env values
```

See [`foundation/README.md`](foundation/README.md).

Best when one team owns all foundation resources and one remote state backend
is acceptable.

### Option B — Standalone modules (separate state per slice)

Apply modules in order; each module has its own `terraform.tfvars` and remote
state backend.

```text
1. deploy/terraform/kms/       (optional; before OpenSearch when domain uses CMK)
2. deploy/terraform/network/   (Lambda SG + optional endpoints)
3. deploy/terraform/opensearch/ (Phase A domain)
4. deploy/terraform/ecr/       (repository only; image build/push stays manual)
5. sam deploy                  (Path B step 7)
6. OpenSearch Phase B + optional CMK Phase B (update tfvars, terraform apply)
```

Module READMEs: [`network/`](network/README.md), [`kms/`](kms/README.md),
[`ecr/`](ecr/README.md), [`opensearch/`](opensearch/README.md).

Best when different teams own KMS, network, search, and image registry with
separate state and approval gates.

### Option C — Hybrid

Examples:

- Existing CMK and VPC; Terraform only for [`network/`](network/) SG +
  [`opensearch/`](opensearch/)
- Foundation with `enable_kms=false` and `existing_kms_key_arn` set
- Configurator-generated `customer-default.env` + standalone OpenSearch tfvars

## Path B apply order (Terraform path)

Regardless of layout, preserve this order relative to SAM:

```text
optional CMK (Phase A key policy)
  -> network (Lambda SG; pass IDs to OpenSearch tfvars)
  -> OpenSearch Phase A
  -> Bedrock enablement (manual)
  -> JWT / IdP (manual)
  -> ECR repo (Terraform) + image build/push (manual)
  -> sam deploy
  -> OpenSearch Phase B (Lambda role ARNs in domain policy)
  -> optional CMK Phase B (Lambda role ARNs in key policy)
```

Copy `terraform output sam_environment` (or merge outputs from standalone
modules) into `customer-default.env` before SAM deploy.

## Path B configurator

[`scripts/configure_path_b.py`](../../scripts/configure_path_b.py) writes
`customer-default.env`, OpenSearch `terraform.tfvars` when creating a domain,
and `path-b-remaining-steps.md`. It does **not** run `terraform apply`.

For foundation layout, copy
[`foundation/terraform.tfvars.example`](foundation/terraform.tfvars.example) to
`foundation/terraform.tfvars` using answers from the configurator and module
READMEs.

## Operator runbooks

| Runbook | Terraform pointer |
| --- | --- |
| [`VPC_NETWORK_PREREQUISITES.md`](../../docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md) | [`network/`](network/) |
| [`KMS_CUSTOMER_KEY.md`](../../docs/operations/deployment/KMS_CUSTOMER_KEY.md) | [`kms/`](kms/) |
| [`DEPLOYMENT_IMAGE_STEPS.md`](../../docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) | [`ecr/`](ecr/) (repo only) |
| [`OPENSEARCH_PROVISIONING.md`](../../docs/operations/deployment/OPENSEARCH_PROVISIONING.md) | [`opensearch/`](opensearch/) |

## Shared requirements

- Terraform **1.6+**, AWS provider **6.x**
- Partition **`aws`**, region **`us-east-1`** only
- Approved **12-digit** `aws_account_id` in every module
- Customer-owned **remote state** (no committed backend block)
- Explicit customer approval before every `terraform apply`

## SAM remains required

Terraform provisions customer-owned foundation. The product Lambda stack, API
Gateway, S3 buckets, queues, and IAM for application functions are created by
**SAM** using values from `customer-default.env`.

Normative SAM preset runbook:
[`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md).
