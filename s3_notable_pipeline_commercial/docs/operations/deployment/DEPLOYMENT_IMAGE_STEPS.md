# Commercial AWS Lambda Image Build and Deployment

Path B Terraform deploys one image to the analyzer, case embedding, RAG
ingestion, and portal functions. Paths A/C retain the legacy SAM template.
Handler commands are overridden per function. The release image must be stored
in the customer's `us-east-1` ECR repository and referenced by digest.

Partition `aws`, region `us-east-1` only. Before ECR push or infrastructure apply, follow
the live mutation gate in [`../../../README.md#2-universal-prerequisites`](../../../README.md#2-universal-prerequisites)
(account ID, partition, region, role/profile, stack name, change set, explicit
customer approval).

**Path B:** build, push, and record the immutable `image_digest` in
`deploy/terraform/customer_default/terraform.tfvars` before the full plan.

**Path B image step**:
[`../../../README.md#path-b--customer-default`](../../../README.md#path-b--customer-default).

## Path B ECR bootstrap

If the repository does not exist, create it from the same Path B root:

```bash
bash scripts/setup-and-deploy.sh --bootstrap-ecr
# Review the saved ECR-only plan.
bash scripts/setup-and-deploy.sh --bootstrap-ecr --apply
terraform -chdir=deploy/terraform/customer_default output ecr_repository_uri
```

Terraform does not build or push the image and does not use a Docker provider or
provisioner.

## Build Contract

Run from the commercial project root:

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<commercial-account-id>
export IMAGE_REPO=notable-analyzer-s3
export IMAGE_TAG=<immutable-release-or-git-sha>
export ECR_REPOSITORY_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_REPO
```

The Dockerfile defaults to the AWS Lambda Python 3.12 public image for local
development. Production builds should use a customer-approved mirror pinned to
an immutable digest:

```bash
docker buildx build \
  --platform linux/amd64 \
  --build-arg LAMBDA_BASE_IMAGE=<approved-registry>/lambda-python@sha256:<digest> \
  -f deploy/docker/Dockerfile \
  -t $ECR_REPOSITORY_URI:$IMAGE_TAG .
```

Create the repository if needed, authenticate, and push:

```bash
aws ecr describe-repositories --repository-names $IMAGE_REPO --region $AWS_REGION \
  >/dev/null 2>&1 || aws ecr create-repository \
  --repository-name $IMAGE_REPO --region $AWS_REGION

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker push $ECR_REPOSITORY_URI:$IMAGE_TAG
export IMAGE_DIGEST=$(aws ecr describe-images \
  --repository-name $IMAGE_REPO \
  --image-ids imageTag=$IMAGE_TAG \
  --region $AWS_REGION \
  --query 'imageDetails[0].imageDigest' --output text)
test "${IMAGE_DIGEST#sha256:}" != "$IMAGE_DIGEST"
```

Pull the digest-qualified artifact before promotion:

```bash
docker pull $ECR_REPOSITORY_URI@$IMAGE_DIGEST
```

## Deployment contract

Required deploy parameters (core stack):

| Parameter | Value |
| --- | --- |
| `EcrRepositoryUri` | Repository URI without tag or digest |
| `ImageDigest` | ECR `sha256:...` digest |
| `AwsAccountId` | 12-digit commercial AWS account ID |
| `BedrockAnalysisModelId` | Customer-approved model or inference-profile ID |
| `BedrockAnalysisModelArn` | Exact ARN for least-privilege `bedrock:InvokeModel` IAM |
| `InputBucketName` | Globally unique input bucket |
| `OutputBucketName` | Globally unique output bucket |
| `DeploymentRegion` | `us-east-1` |
| `DeploymentPartition` | `aws` |

For Path B, set the equivalent Terraform inputs and follow
[`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md).
Paths A/C map these values to their legacy SAM parameters.

`scripts/setup-and-deploy.ps1` and `scripts/setup-and-deploy.sh` plan or apply
Path B Terraform only. They do not build, tag, or push the container image.

Vector, portal, and integration capabilities require additional values in
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md)
and [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md).
CloudFormation rules fail deployment when tenant, endpoint, VPC, JWT grants,
or other required inputs for an enabled capability are missing.

## Rollback (failed release)

Rollback is **redeploy**, not infrastructure deletion.

1. Identify the last known-good immutable `ImageDigest` for the same ECR repository (release evidence or ECR describe-images).
2. Path B: restore the previous approved Terraform inputs. Paths A/C: restore the previous CloudFormation template and parameters.
3. Obtain explicit customer approval for the redeploy.
4. Path B: review and apply a fresh Terraform plan with the previous digest. Paths A/C: redeploy the previous SAM digest and parameters.
5. Validate recovery: core smoke ([`../../../README.md`](../../../README.md) section 5), OpenSearch preflight if vector capabilities are enabled ([`../../testing/TESTING.md`](../../testing/TESTING.md)), portal `/ready` when applicable.

Record rollback digest, deploy time, and validation outcome in release evidence.

## Release Evidence

Record the source commit, base-image digest, final image digest, ECR repository,
Terraform plan or CloudFormation change set, test results, smoke-test results,
and rollback digest. Do not use `latest` as a release reference.

## Next

- **Path A step 3:** legacy SAM — [`../../../README.md`](../../../README.md#path-a-core-only)
- **Path B full plan/apply:** [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- **Path C step 6:** SAM deploy with profile-specific parameters — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- Path B post-deploy (portal SPA, RAG ingest, live acceptance): [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md#post-deploy)
