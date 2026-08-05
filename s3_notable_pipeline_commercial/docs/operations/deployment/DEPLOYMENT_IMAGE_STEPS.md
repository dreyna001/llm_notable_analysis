# Commercial AWS Lambda Image Build and Deployment

The SAM and CloudFormation templates deploy one image to the analyzer, case
embedding, RAG ingestion, disposition sync, and portal functions. Handler
commands are overridden per function. The release image must be stored in the
customer's `us-east-1` ECR repository and referenced by digest.

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

Required image parameters:

| Parameter | Value |
| --- | --- |
| `EcrRepositoryUri` | Repository URI without tag or digest |
| `ImageDigest` | ECR `sha256:...` digest |
| `DeploymentRegion` | `us-east-1` |
| `DeploymentPartition` | `aws` |

Build and deploy:

```bash
sam build -t deploy/aws/template-sam.yaml
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name notable-analyzer-stack \
  --region us-east-1 \
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
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md).
CloudFormation rules fail deployment when tenant, endpoint, VPC, or JWT grants
required by an enabled capability are missing.

## Release Evidence

Record the source commit, base-image digest, final image digest, ECR repository,
rendered template, CloudFormation change set, test results, smoke-test results,
and rollback digest. Do not use `latest` as a release reference.
