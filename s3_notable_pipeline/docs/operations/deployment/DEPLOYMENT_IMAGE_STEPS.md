# GovCloud Lambda Image Build and Deployment

The SAM and CloudFormation templates deploy one image to the analyzer, case
embedding, RAG ingestion, disposition sync, and portal functions. Handler
commands are overridden per function. The release image must be stored in the
customer's `us-gov-east-1` ECR repository and referenced by digest.

Partition `aws-us-gov`, region `us-gov-east-1` only. Before ECR push or `sam deploy`, follow
the live mutation gate in [`../../../README.md`](../../../README.md#1-prerequisites)
(account ID, partition, region, role/profile, stack name, change set, explicit
customer approval).

**Path B step 6** (digest-qualified image before SAM):
[`../../../README.md`](../../../README.md#path-b-customer-default).

## Build Contract

Run from `s3_notable_pipeline/`:

```bash
export AWS_REGION=us-gov-east-1
export AWS_ACCOUNT_ID=<govcloud-account-id>
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

Required image parameters:

| Parameter | Value |
| --- | --- |
| `EcrRepositoryUri` | Repository URI without tag or digest |
| `ImageDigest` | ECR `sha256:...` digest |
| `DeploymentRegion` | `us-gov-east-1` |
| `DeploymentPartition` | `aws-us-gov` |

Build and deploy:

```bash
sam build -t deploy/aws/template-sam.yaml
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name notable-analyzer-stack \
  --region us-gov-east-1 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    AwsAccountId=$AWS_ACCOUNT_ID \
    EcrRepositoryUri=$ECR_REPOSITORY_URI \
    ImageDigest=$IMAGE_DIGEST \
    BedrockAnalysisModelId=<approved-model-or-profile> \
    InputBucketName=<customer-input-bucket> \
    OutputBucketName=<customer-output-bucket>
```

Enabled OpenSearch or portal capabilities additionally require the values in
[`GOVCLOUD_CUSTOMER_CONFIGURATION.md`](GOVCLOUD_CUSTOMER_CONFIGURATION.md).
Provision the OpenSearch domain first:
[`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md).
CloudFormation rules fail deployment when tenant, endpoint, VPC, or JWT grants
required by an enabled capability are missing.

## Rollback (failed release)

Rollback is **redeploy**, not stack deletion.

1. Identify the last known-good immutable `ImageDigest` for the same ECR repository.
2. Review the previous CloudFormation template/parameters or change set.
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
- **Path B step 7:** [`GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md`](GOVCLOUD_CUSTOMER_DEFAULT_DEPLOYMENT.md)
- **Path C step 6:** SAM deploy with profile-specific parameters — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
