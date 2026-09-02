# S3 Notable Pipeline

Commercial AWS product for security-notable analysis in partition `aws`, region
`us-east-1` only. Deployment scripts fail closed outside that boundary.

**Deployers start here.** Work through sections 2 and 3 in order, pick one path in
section 4, follow each linked runbook through validation. Topic shortcuts and the
documentation index live in [`docs/README.md`](docs/README.md).

This service processes security notables uploaded to S3, runs LLM-based ATT&CK
analysis (Bedrock), and sends results to one of two sinks:

- `s3` (test mode): write markdown reports and Bedrock JSON (`llm_response`) back to S3
- `notable_rest`: write the markdown and JSON to S3 and update the Splunk notable comment via REST

## 2) Universal prerequisites

Complete this section **before** choosing Path A, B, or C.

### Tools and access

| Requirement | Notes |
| --- | --- |
| Commercial AWS account in `us-east-1` | Customer-approved Bedrock model access |
| AWS CLI | Configured (`aws configure`) |
| `COMMERCIAL_AWS_ACCOUNT_ID` | Set to the approved 12-digit account; deployment scripts compare it with the active STS caller |
| Terraform 1.10+ | Required for Path B remote state locking |
| AWS SAM CLI | Install: [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) — no dedicated install runbook in this repo |
| Docker | Required for Lambda image build |
| Lambda image in ECR | Published to customer commercial AWS ECR in `us-east-1` with immutable digest (`EcrRepositoryUri` + `ImageDigest`) — see image runbook on your path |

Quick checks:

```bash
aws sts get-caller-identity
sam --version
terraform version
docker --version
```

### Live AWS mutation gate

Before **any** live AWS mutation (ECR push, Terraform apply, `sam deploy`, key
policy update):

1. Confirm STS account ID matches `COMMERCIAL_AWS_ACCOUNT_ID`
2. Confirm partition `aws` and region `us-east-1`
3. Confirm active CLI role or profile and target stack name
4. Review the Terraform plan or CloudFormation change set
5. Obtain explicit customer approval for that mutation

## 3) Before you choose a path

Read these once. They apply to every deploy path and explain what you provision
vs what the product stack creates.

### 3.1 Ownership and scope (required)

[`docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md) — customer-provisioned resources (VPC, OpenSearch domain, IdP, CMK, ECR image, Bedrock access) vs stack-created resources (Lambdas, queues, buckets, API Gateway).

### 3.2 Customer values checklist

[`docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md) — living checklist of account, network, model, identity, and retention inputs. Fill values as you complete each runbook on your path; do not wait until SAM deploy.

### 3.3 Pick your path

| Path | When to use | Bundle |
| --- | --- | --- |
| **A — Core only** | First stack, analysis only, no RAG or portal | `core` |
| **B — Customer-default** | On-prem `core,rag,analyst_portal` parity on commercial AWS | `core,rag,analyst_portal` |
| **C — Custom profiles** | Specific bundles such as `spl_readonly` or `action_gated` | You choose |

Each runbook ends with a **Next** line for path navigation. Stay on one path until you reach [`docs/testing/TESTING.md`](docs/testing/TESTING.md).

### 3.4 Path B — prepare before step 1

If you chose **Path B**, set up working files now so each runbook can drop values
into one place. Path B uses only the native Terraform root for infrastructure and
application deployment.

| Prepare now | Purpose |
| --- | --- |
| Run `python scripts/configure_path_b.py` | Writes `deploy/terraform/customer_default/terraform.tfvars` and `path-b-remaining-steps.md` |
| Or copy [`deploy/terraform/customer_default/terraform.tfvars.example`](deploy/terraform/customer_default/terraform.tfvars.example) to `terraform.tfvars` | Manual input path |
| Read [`deploy/terraform/README.md`](deploy/terraform/README.md) | Path B root, bootstrap, plan, apply, and output contract |
| Confirm an approved remote state backend | State may contain customer infrastructure metadata |
| Coordinate network and IdP owners early | VPC/subnets and JWT/OIDC remain customer inputs |

Path B deploy order at a glance (details in section 4):

```text
VPC/network + Bedrock + JWT/IdP inputs -> optional ECR bootstrap -> immutable image
  -> one Terraform plan/apply -> RAG ingest -> portal SPA -> smoke tests
```

Terraform creates deterministic application IAM roles and wires them into the
OpenSearch and optional KMS policies in the same full apply. Path B has no manual
role-copy phase.

Normative Path B runbook:
[`docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md).

## 4) Deploy — follow your path

### Path A — Core only

Follow in order:

1. [`docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`](docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) — enable customer-approved Bedrock analysis models in the account
2. [`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — build, push, and record `ImageDigest` before SAM
3. **Deploy** with `CapabilityProfiles=core` using the legacy SAM template
4. [`docs/testing/TESTING.md`](docs/testing/TESTING.md) — unit tests and core smoke validation

Deploy commands (Path A remains SAM):

```powershell
sam build -t deploy/aws/template-sam.yaml
sam deploy --guided --region us-east-1 --template-file .aws-sam/build/template.yaml
```

```bash
sam build -t deploy/aws/template-sam.yaml
sam deploy --guided --region us-east-1 --template-file .aws-sam/build/template.yaml
```

Pass `EcrRepositoryUri` and `ImageDigest` via guided deploy, `samconfig.toml`, or
parameter overrides. `setup-and-deploy.*` is reserved for Terraform Path B.

Infrastructure template: [`deploy/aws/template-sam.yaml`](deploy/aws/template-sam.yaml).
Runtime env reference: [`config.env.example`](config.env.example).

### Path B — Customer-default

Bundle: `core,rag,analyst_portal`. Complete [section 3.4](#34-path-b--prepare-before-step-1) first.

**Do not skip VPC, JWT, Bedrock access, or the immutable image step.**

| Step | Runbook | Collect / record |
| --- | --- | --- |
| 1 | [`VPC_NETWORK_PREREQUISITES.md`](docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md), [`BEDROCK_ACCOUNT_ENABLEMENT.md`](docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md), [`PORTAL_JWT_IDENTITY.md`](docs/operations/deployment/PORTAL_JWT_IDENTITY.md) | Fill customer network, model, and JWT inputs in `terraform.tfvars` |
| 2 (greenfield ECR only) | [`DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) | Run the ECR bootstrap target, push the image, record `image_digest` |
| 3 | [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md) | Review one full Terraform plan and apply it |
| 4 | [`KNOWLEDGE_BASE_OPERATIONS.md`](docs/operations/rag/KNOWLEDGE_BASE_OPERATIONS.md) | SOC and Splunk dictionary corpora ingest |
| 5 | [`ANALYST_PORTAL_OPERATIONS.md`](docs/operations/analyst_portal/ANALYST_PORTAL_OPERATIONS.md), [`frontend/analyst-portal/README.md`](frontend/analyst-portal/README.md) | Build and upload analyst portal SPA |
| 6 | [`TESTING.md`](docs/testing/TESTING.md) | Live customer-default acceptance |

Follow the numbered steps in order — use the **Next** line at the bottom of each runbook.

### Path C — Custom profiles

1. [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) — select profile bundles and note mutual exclusions
2. [`docs/operations/deployment/KMS_CUSTOMER_KEY.md`](docs/operations/deployment/KMS_CUSTOMER_KEY.md) — optional production CMK before OpenSearch when the domain uses a CMK
3. If `rag`, `RagIngestionEnabled`, `SplQueryRagEnabled`, or portal case Q&A: [`docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md`](docs/operations/deployment/VPC_NETWORK_PREREQUISITES.md) then [`docs/operations/deployment/OPENSEARCH_PROVISIONING.md`](docs/operations/deployment/OPENSEARCH_PROVISIONING.md) (Phase A) — network prerequisites and domain creation
4. [`docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`](docs/operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) — enable Bedrock models when analysis or embeddings are used
5. If `analyst_portal`: [`docs/operations/deployment/PORTAL_JWT_IDENTITY.md`](docs/operations/deployment/PORTAL_JWT_IDENTITY.md) — configure portal identity before SAM
6. [`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md) — build ECR image, then SAM deploy with profile-specific parameters
7. OpenSearch Phase B and optional CMK Phase B — legacy SAM-only handoff for Path C
8. Profile ops guides from [`docs/operations/README.md`](docs/operations/README.md) — day-two tuning for enabled profiles
9. [`docs/testing/TESTING.md`](docs/testing/TESTING.md) — Wave 1 and portal staging tables for your profile slice

Customer values checklist: [`docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](docs/operations/deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md).

## 5) Validate (all paths end here)

Path-specific checklists live in [`docs/testing/TESTING.md`](docs/testing/TESTING.md).
Core smoke helper (PowerShell 5.1+ or `pwsh`; set `COMMERCIAL_AWS_ACCOUNT_ID` and
`AWS_REGION=us-east-1` first):

```powershell
$env:AWS_REGION = "us-east-1"
$env:COMMERCIAL_AWS_ACCOUNT_ID = "<approved-12-digit-account>"
.\scripts\test-pipeline.ps1
```

Customer-default example:

```powershell
.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,analyst_portal"
```

## 6) Rollback and teardown

**Rollback (failed release, not teardown):** Path B restores the previous approved
Terraform input set and immutable `image_digest`, reviews the plan, and applies it.
Paths A/C redeploy the previous SAM `ImageDigest`. See
[`docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md`](docs/operations/deployment/DEPLOYMENT_IMAGE_STEPS.md)
(Rollback).

**Teardown (destructive — approval required):** stack deletion and bucket emptying are
**irreversible** and are not rollback. After explicit customer approval, use the
resource inventory in
[`docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](docs/operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md)
with customer-approved stack and retained-resource procedures. No automated bulk
deletion workflow is provided.

## 7) Further reading

| Topic | Doc |
| --- | --- |
| Capability profiles and SAM parameters | [`docs/operations/platform/CAPABILITY_PROFILES.md`](docs/operations/platform/CAPABILITY_PROFILES.md) |
| Lambda runtime env contract | [`config.env.example`](config.env.example) |
| Splunk sink modes and writeback | [`docs/operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](docs/operations/integrations/SPLUNK_WRITEBACK_OPERATIONS.md) |
| Operations guides by area | [`docs/operations/README.md`](docs/operations/README.md) |
| Documentation index and topic shortcuts | [`docs/README.md`](docs/README.md) |
| On-prem mirror | [`../llm_notable_analysis_onprem_systemd/docs/`](../llm_notable_analysis_onprem_systemd/docs/) |
