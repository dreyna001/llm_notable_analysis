# Commercial AWS Lambda Image Build and Deployment

The SAM and CloudFormation templates deploy one image to the analyzer, case
embedding, RAG ingestion, disposition sync, and portal functions. Handler
commands are overridden per function. The release image must be stored in the
customer's `us-east-1` ECR repository and referenced by digest.

Partition `aws`, region `us-east-1` only. Before ECR push or `sam deploy`, follow
the live mutation gate in [`../../../README.md`](../../../README.md#1-prerequisites)
(account ID, partition, region, role/profile, stack name, change set, explicit
customer approval).

**Path B step 6** (digest-qualified image before SAM):
[`../../../README.md`](../../../README.md#path-b-customer-default).

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

## Deploy Contract

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

`sam build` and `sam deploy` (full parameter examples and customer-default preset):
[`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
and Path A deploy scripts in [`../../../README.md`](../../../README.md) section 2.

`scripts/setup-and-deploy.ps1` and `scripts/setup-and-deploy.sh` run `sam build`
and `sam deploy` only. They do not build, tag, or push the container image.
Publish the digest-qualified image to ECR before deploy, or include
`EcrRepositoryUri` and `ImageDigest` in `samconfig.toml` / guided prompts.

Vector, portal, and integration capabilities require additional values in
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md)
and [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md).
CloudFormation rules fail deployment when tenant, endpoint, VPC, JWT grants,
or other required inputs for an enabled capability are missing.

## Rollback (failed release)

Rollback is **redeploy**, not stack deletion. Do not use `sam delete` as rollback.

1. Identify the last known-good immutable `ImageDigest` for the same ECR repository (release evidence or ECR describe-images).
2. Review the previous CloudFormation template/parameters or change set; confirm the same stack name, `EcrRepositoryUri`, and configuration except `ImageDigest`.
3. Obtain explicit customer approval for the redeploy.
4. Run `sam deploy` with the previous `ImageDigest` (and prior parameter set if it changed).
5. Validate recovery: core smoke ([`../../../README.md`](../../../README.md) section 3), OpenSearch preflight if vector capabilities are enabled ([`../../testing/TESTING.md`](../../testing/TESTING.md)), portal `/ready` when applicable.

Record rollback digest, deploy time, and validation outcome in release evidence.

## Release Evidence

Record the source commit, base-image digest, final image digest, ECR repository,
rendered template, CloudFormation change set, test results, smoke-test results,
and rollback digest. Do not use `latest` as a release reference.

## Next

- **Path A step 3:** `setup-and-deploy.*` — [`../../../README.md`](../../../README.md#path-a-core-only)
- **Path B step 7:** [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- **Path C step 6:** SAM deploy with profile-specific parameters — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- Post-deploy (OpenSearch Phase B, portal SPA, RAG ingest): [`COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md#post-deploy-required-for-full-customer-default)
