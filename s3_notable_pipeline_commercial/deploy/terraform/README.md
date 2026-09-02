# Commercial AWS Terraform

Commercial Path B uses one native Terraform root:
[`customer_default/`](customer_default/). It creates the customer-default
foundation and application in one state and one reviewed full plan/apply.

The older standalone modules and [`foundation/`](foundation/) remain available
for legacy Path A/C or separately owned foundation work. They are not the Path B
application deployment workflow.

## Path B coverage

| Area | Path B owner |
| --- | --- |
| Existing VPC and private subnets | Customer input |
| Lambda security group and optional endpoints | Terraform |
| Optional KMS key | Terraform, or customer-supplied ARN |
| ECR repository | Terraform, or customer-supplied repository |
| Immutable container image build and push | Customer release process |
| VPC-only OpenSearch domain | Terraform, or customer-supplied domain |
| Analyzer, case-embed, and RAG-ingestion Lambdas | Terraform `application_core` module |
| Queues, DLQs, buckets, CaseIndex, logs, and alarms | Terraform `application_core` module |
| Portal Lambda, JWT authorizer, API routes, and private UI bucket | Terraform `application_portal` module |
| Bedrock access and model approval | Customer account owner |
| JWT identity provider | Customer identity owner |

Application IAM role names are deterministic. The same full apply passes their
ARNs directly to the OpenSearch domain policy and optional KMS policy. Path B
does not require a later role lookup, policy edit, or second apply.

## Prerequisites

- Terraform 1.10+ for the Path B root and AWS provider 6.x
- Commercial partition `aws`, region `us-east-1`
- Approved 12-digit AWS account ID
- Existing VPC and private subnets
- Customer-approved remote state backend
- Bedrock model access
- JWT issuer, audience, and at least one analyst role or scope
- Explicit approval before `terraform apply`

## Configure

```bash
python scripts/configure_path_b.py
```

Or:

```bash
cp deploy/terraform/customer_default/terraform.tfvars.example \
  deploy/terraform/customer_default/terraform.tfvars
# Edit every placeholder.
```

## Image bootstrap

If an approved digest-qualified image already exists, skip this section.

For a new ECR repository, use the same root in ECR-only mode:

```bash
export AWS_REGION=us-east-1
export COMMERCIAL_AWS_ACCOUNT_ID="<approved-12-digit-account>"

bash scripts/setup-and-deploy.sh --bootstrap-ecr
# Review deploy/terraform/customer_default/bootstrap-ecr.tfplan.
bash scripts/setup-and-deploy.sh --bootstrap-ecr --apply
terraform -chdir=deploy/terraform/customer_default output ecr_repository_uri
```

Build and push the image outside Terraform. Set `image_digest` to the immutable
`sha256:<64-lowercase-hex>` digest. Terraform provisioners and Docker providers
are intentionally not used.

## Full plan and apply

```bash
bash scripts/setup-and-deploy.sh
# Review deploy/terraform/customer_default/customer-default.tfplan.
bash scripts/setup-and-deploy.sh --apply
```

PowerShell:

```powershell
$env:AWS_REGION = "us-east-1"
$env:COMMERCIAL_AWS_ACCOUNT_ID = "<approved-12-digit-account>"
.\scripts\setup-and-deploy.ps1
.\scripts\setup-and-deploy.ps1 -Apply
```

The default command is plan-only. `--apply` or `-Apply` is required for a live
mutation. Both scripts run account, partition, region, formatting, initialization,
and validation checks before planning.

## Evidence and validation

Run the same Terraform gate used by pull requests:

```bash
python3 -m pip install -r requirements-terraform.txt
bash scripts/check-terraform.sh
```

The gate uses Terraform 1.15.9 and Checkov 3.3.16. It checks formatting,
initializes each Terraform directory without a backend, validates it, runs the
focused Terraform contract tests, and scans the Terraform tree with Checkov.

Repository administrators: complete the one-time
[`GITHUB_TERRAFORM_CI_SETUP.md`](../../docs/operations/deployment/GITHUB_TERRAFORM_CI_SETUP.md)
guide to enable Actions and require this gate before merging.

Keep these with the customer change record:

- reviewed saved plan
- `terraform output -json`
- immutable image digest
- live acceptance results from
  [`DEPLOYMENT_READINESS_AND_LIFECYCLE.md`](../../docs/operations/deployment/DEPLOYMENT_READINESS_AND_LIFECYCLE.md)

Do not commit plan files, state, credentials, tokens, or raw JWTs.

## Baseline boundary

Path B deploys `core,rag,analyst_portal`: analyzer, case embedding, RAG ingestion,
portal API/UI, their queues and DLQs, required storage, CaseIndex, logs, alarms,
API routes, and JWT auth. Disabled optional profiles are not carried forward as
idle infrastructure. Side-effect, disposition, closed-ticket, and chat-history
resources require a separately approved custom-profile deployment.

## Destruction

`terraform destroy` is teardown, not rollback. It may remove customer data and
requires a separate approved teardown plan. Normal rollback restores the previous
approved Terraform inputs and immutable image digest, then reviews and applies a
new plan.
