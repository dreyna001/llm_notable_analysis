# Commercial AWS customer-default deployment

Path B deploys `core,rag,analyst_portal` to commercial AWS `us-east-1` from the
single native Terraform root
[`deploy/terraform/customer_default/`](../../../deploy/terraform/customer_default/).

## Required customer inputs

- approved AWS account, role, remote state backend, VPC, and private subnets
- Bedrock analysis model ID, exact ARN, and any inference-profile model ARNs
- JWT issuer, audience, optional tenant, and at least one analyst role or scope
- globally unique input, output, and portal UI bucket names
- OpenSearch administrator principals when Terraform creates the domain
- immutable ECR image digest
- alert topic and retention values required by customer policy

Run the guided configurator or copy the example:

```bash
python scripts/configure_path_b.py
```

```bash
cp deploy/terraform/customer_default/backend.hcl.example \
  deploy/terraform/customer_default/backend.hcl
cp deploy/terraform/customer_default/terraform.tfvars.example \
  deploy/terraform/customer_default/terraform.tfvars
# Edit every placeholder.
```

Customer-owned prerequisite details:

- [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md)
- [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md)
- [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md)
- [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)

## Greenfield ECR bootstrap

Skip this section when an approved digest-qualified image already exists.

```bash
export AWS_REGION=us-east-1
export COMMERCIAL_AWS_ACCOUNT_ID="<approved-12-digit-account>"

bash scripts/setup-and-deploy.sh --bootstrap-ecr
# Review deploy/terraform/customer_default/bootstrap-ecr.tfplan.
bash scripts/setup-and-deploy.sh --bootstrap-ecr --apply
terraform -chdir=deploy/terraform/customer_default output ecr_repository_uri
```

Build and push the image using [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md),
then set `image_digest` in `terraform.tfvars`. A full plan fails closed unless the
image reference is pinned to `sha256:<64-lowercase-hex>`.

## Plan

```bash
export AWS_REGION=us-east-1
export COMMERCIAL_AWS_ACCOUNT_ID="<approved-12-digit-account>"

bash scripts/setup-and-deploy.sh
```

Review the saved plan for:

- approved account, region, names, tags, and remote-state workspace
- expected creates, updates, replacements, and cost-bearing resources
- digest-qualified Lambda image URI
- VPC-only Lambda and OpenSearch configuration
- separate least-privilege analyzer, case-embed, RAG-ingestion, and portal roles
- OpenSearch and optional KMS policies containing those deterministic role ARNs
- analyzer, case-embed, and RAG-ingestion queues with DLQs and alarms
- JWT authorizer, issuer, audience, and analyst role/scope enforcement
- encryption, retention, logging, and alert settings

Stop for any unexplained replacement, public access, wildcard data-plane grant,
mutable image, missing DLQ, or missing JWT grant.

## Apply

After customer approval:

```bash
bash scripts/setup-and-deploy.sh --apply
```

PowerShell:

```powershell
$env:AWS_REGION = "us-east-1"
$env:COMMERCIAL_AWS_ACCOUNT_ID = "<approved-12-digit-account>"
.\scripts\setup-and-deploy.ps1
.\scripts\setup-and-deploy.ps1 -Apply
```

The apply prints `terraform output -json`. Store it with the reviewed plan and
change approval. No application role lookup or policy edit follows the apply.

## Path B baseline inventory

This inventory is the migration contract from the former customer-default SAM
preset.

| Area | Terraform Path B resources |
| --- | --- |
| Core compute | Analyzer, case-embed, and RAG-ingestion Lambda functions with deterministic IAM roles |
| Queues | Analyzer, case-embed, and RAG-ingestion queues, one DLQ per queue, redrive policy, S3 notification policy |
| Storage | Input and output buckets, private portal UI bucket, CaseIndex table |
| Search and encryption | VPC-only OpenSearch domain or existing domain, optional KMS key or existing key, direct application-role policy wiring |
| Portal | Portal Lambda, HTTP API, JWT authorizer, integration, routes, stage, invoke permission |
| Operations | Dedicated log groups, error/depth/age/DLQ alarms, deployment outputs and JSON report |

Customer-default settings remain fixed to the former preset intent:

| Former SAM setting | Terraform Path B value |
| --- | --- |
| `CapabilityProfiles` | `core,rag,analyst_portal` |
| `SplunkSinkMode` | `s3` |
| `HtmlReportEnabled` | `false` |
| `RagEnabled` | `true` |
| `RagIngestionEnabled` | `true` |
| `SplQueryRagEnabled` | `true` |
| `PortalEnabled` | `true` |
| `PortalAuthMode` | `jwt` |
| `CaseArchiveEnabled` | `true` |
| `CaseQaEnabled` | `true` |
| OpenSearch indexes | `soc_knowledge`, `splunk_dictionary`, `case_chunks` |

The native baseline intentionally omits resources that the former template
created even while their profiles were disabled: side-effect idempotency,
disposition sync, closed-ticket sync/embed, and chat-history resources. Those
belong to separately approved custom-profile work and are not idle Path B cost or
permission surface.

## Post-deploy

1. Load the approved SOC and Splunk dictionary corpora using
   [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md).
2. Build and upload the analyst portal SPA using
   [`ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
3. Run every applicable live acceptance check in
   [`DEPLOYMENT_READINESS_AND_LIFECYCLE.md`](DEPLOYMENT_READINESS_AND_LIFECYCLE.md)
   and [`TESTING.md`](../../testing/TESTING.md).

```powershell
$env:AWS_REGION = "us-east-1"
$env:COMMERCIAL_AWS_ACCOUNT_ID = "<approved-12-digit-account>"
.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,analyst_portal"
```

## Rollback

Restore the last approved `terraform.tfvars` values and immutable image digest,
create and review a new saved plan, then apply it through the same approval path.
Data-store, KMS, OpenSearch, or bucket deletion is teardown, not rollback.
