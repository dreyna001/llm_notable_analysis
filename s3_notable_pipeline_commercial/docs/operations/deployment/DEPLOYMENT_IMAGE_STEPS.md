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
    BedrockAnalysisModelArn=<approved-model-or-profile-arn> \
    InputBucketName=<customer-input-bucket> \
    OutputBucketName=<customer-output-bucket>
```

`scripts/setup-and-deploy.ps1` and `scripts/setup-and-deploy.sh` run `sam build`
and `sam deploy` only. They do not build, tag, or push the container image.
Publish the digest-qualified image to ECR before deploy, or include
`EcrRepositoryUri` and `ImageDigest` in `samconfig.toml` / guided prompts.

Enabled OpenSearch, portal, RAG ingestion, or disposition-sync capabilities
additionally require the values in
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md)
and profile detail in
[`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md).
CloudFormation rules fail deployment when tenant, endpoint, VPC, JWT grants,
or other required inputs for an enabled capability are missing.

## Post-Deploy Steps (when enabled)

| Capability | After `sam deploy` |
| --- | --- |
| `analyst_portal` | Build `frontend/analyst-portal`, upload `dist/` to `PortalUiBucketName`, configure JWT/CORS; see [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| `rag` | Load approved corpora to S3, publish manifest to trigger ingestion; see [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| ServiceNow disposition sync | Verify EventBridge schedule, field maps, and sync token secret; see [`../integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](../integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) |

## Release Evidence

Record the source commit, base-image digest, final image digest, ECR repository,
rendered template, CloudFormation change set, test results, smoke-test results,
and rollback digest. Do not use `latest` as a release reference.
