# Missing Lambda Image Deployment Steps

## What Is Missing

The current deployment flow does not create the Lambda container image.

`deploy/aws/template-sam.yaml` expects `ImageUri` to point to an existing ECR image:

```yaml
PackageType: Image
ImageUri: !Ref ImageUri
```

That means `sam deploy` only references an image that already exists in ECR. It does not create the ECR repository, build the Docker image, tag it, or push it.

The `deploy/docker/Dockerfile` is the image recipe, but its current `FROM` line is a placeholder and must be replaced with a real approved Lambda Python 3.12 base image before building:

```dockerfile
FROM <image>.dkr.ecr.us-east-1.amazonaws.com/ironbank/lambda.python:312
```

## ECR URI Format

Example:

```text
123456789012.dkr.ecr.us-east-1.amazonaws.com/notable-analyzer-s3:latest
```

Parts:

```text
123456789012        AWS account ID
dkr.ecr             AWS ECR Docker registry endpoint
us-east-1           AWS region
amazonaws.com       AWS domain
notable-analyzer-s3 ECR repository name
latest              image tag
```

`dkr` means Docker registry. It is part of the standard AWS ECR registry hostname.

## How To Choose The Repo

ECR repositories are scoped to an AWS account and region.

The repo is selected by the image URI you use:

```text
<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:<tag>
```

For the current YAML, set the full image URI through `ImageUri`:

```bash
sam deploy \
  --parameter-overrides \
    AwsAccountId=<account-id> \
    ImageUri=<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:<tag>
```

If using the SAM YAML alternative, set the repo with `--image-repository`:

```bash
sam deploy \
  --image-repository <account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>
```

Use an existing repo by putting its repo name in `<repo-name>`. Create a new repo only if no suitable repo exists.

## Where To Find The Values

AWS account ID:

```bash
aws sts get-caller-identity --query Account --output text
```

Current AWS CLI region:

```bash
aws configure get region
```

Existing ECR repositories in a region:

```bash
aws ecr describe-repositories --region us-east-1
```

One specific ECR repo URI:

```bash
aws ecr describe-repositories \
  --repository-names notable-analyzer-s3 \
  --region us-east-1 \
  --query 'repositories[0].repositoryUri' \
  --output text
```

Existing image tags in a repo:

```bash
aws ecr describe-images \
  --repository-name notable-analyzer-s3 \
  --region us-east-1 \
  --query 'imageDetails[].imageTags[]' \
  --output text
```

## Required Order

Run these from `s3_notable_pipeline/` after replacing placeholders.

The `export` values below are optional shell shortcuts. You can either use variables, paste the full values directly into each command, or update `deploy/aws/template-sam.yaml` so SAM builds and pushes the image from `deploy/docker/Dockerfile`.

You do not have to create a new ECR repository if one already exists. Use the existing repository name in `IMAGE_REPO` and skip the `aws ecr create-repository` step.

Right now, `us-east-1` is not only an example region. `deploy/aws/template-sam.yaml` currently hard-codes the Bedrock inference profile ARN to `us-east-1`, so changing `AWS_REGION` without also updating the template can break deployment or runtime Bedrock calls.

If Lambda fails with `not authorized to perform: bedrock:InvokeModel`, check the deployed Lambda role and `BEDROCK_MODEL_ID` together. The role policy must allow `bedrock:InvokeModel` on the exact model or inference profile ARN used by `BEDROCK_MODEL_ID`; if those differ, redeploy SAM with the corrected parameter/template before troubleshooting Bedrock model access.

Compressed input support is gzip-only. The Lambda accepts UTF-8 text/JSON directly, plus single-payload gzip inputs such as `.json.gz` and `.txt.gz`. It does not process ZIP archives or multi-file compressed uploads. Gzip input is rejected if the decompressed payload exceeds `MaxDecompressedInputBytes`.

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<account-id>
export IMAGE_REPO=notable-analyzer-s3
export IMAGE_TAG=latest
export MAX_DECOMPRESSED_INPUT_BYTES=1048576
export IMAGE_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_REPO:$IMAGE_TAG
```

This guide uses `latest` to keep scratch deployments simple. For customer environments, use whatever image-tagging convention the customer already uses, such as a build number, date tag, or git SHA.

```bash
aws ecr create-repository \
  --repository-name $IMAGE_REPO \
  --region $AWS_REGION
```

Skip this command if the ECR repository already exists.

```bash
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

```bash
docker build -f deploy/docker/Dockerfile -t $IMAGE_REPO:$IMAGE_TAG .
```

```bash
docker tag $IMAGE_REPO:$IMAGE_TAG $IMAGE_URI
docker push $IMAGE_URI
```

```bash
sam build -t deploy/aws/template-sam.yaml
```

```bash
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

When prompted for `ImageUri`, use:

```bash
$IMAGE_URI
```

For non-guided deploy when `samconfig.toml` already exists:

```bash
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --parameter-overrides \
    AwsAccountId=$AWS_ACCOUNT_ID \
    MaxDecompressedInputBytes=$MAX_DECOMPRESSED_INPUT_BYTES \
    ImageUri=$IMAGE_URI
```

For a first-time non-guided deploy, include the stack name, region, capabilities, and required parameters explicitly:

```bash
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name notable-analyzer-stack \
  --region $AWS_REGION \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    InputBucketName=<globally-unique-input-bucket-name> \
    OutputBucketName=<globally-unique-output-bucket-name> \
    SplunkSinkMode=s3 \
    AwsAccountId=$AWS_ACCOUNT_ID \
    MaxDecompressedInputBytes=$MAX_DECOMPRESSED_INPUT_BYTES \
    ImageUri=$IMAGE_URI
```

## Alternative: Update SAM YAML

Instead of manually building, tagging, pushing, and passing `ImageUri`, update `deploy/aws/template-sam.yaml` so SAM uses the local `deploy/docker/Dockerfile`.

Change the function to remove `ImageUri` and add image metadata:

```yaml
NotableAnalyzerFunction:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: notable-analyzer-s3
    PackageType: Image
    Timeout: 360
    MemorySize: 512
  Metadata:
    Dockerfile: deploy/docker/Dockerfile
    DockerContext: .
    DockerTag: latest
```

Then run:

```bash
sam build -t deploy/aws/template-sam.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

For non-guided deploy with an existing ECR repo:

```bash
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --image-repository 123456789012.dkr.ecr.us-east-1.amazonaws.com/notable-analyzer-s3
```

This still requires the `deploy/docker/Dockerfile` `FROM` image to be real and pullable.

## SAM Commands: Outputs And Fields

### `sam build -t deploy/aws/template-sam.yaml`

What it generates:

- `.aws-sam/build/` local build directory.
- `.aws-sam/build/template.yaml` built SAM template.
- With the current YAML, it does not create or push the Docker image because `ImageUri` points to an existing ECR image.
- With the SAM YAML alternative, it builds the Docker image from `deploy/docker/Dockerfile` before deploy.

What to check:

```bash
sam build -t deploy/aws/template-sam.yaml
```

Expected result:

```text
Build Succeeded
Built Artifacts  : .aws-sam/build
Built Template   : .aws-sam/build/template.yaml
```

### `sam deploy --guided`

What it generates in AWS:

- CloudFormation stack.
- S3 input bucket.
- S3 output bucket.
- Lambda function.
- Lambda execution role and policies.
- S3 event trigger for `incoming/`.
- Lambda invoke permission for S3.

What it generates locally if you choose to save settings:

- `samconfig.toml`

Use `samconfig.toml` so future deploys can run with:

```bash
sam deploy --template-file .aws-sam/build/template.yaml
```

### Guided Deploy Fields

Stack Name:

```text
notable-analyzer-stack
```

Why: names the CloudFormation stack that owns the deployed resources.

AWS Region:

```text
us-east-1
```

Why: must match the region where Lambda, S3, Bedrock access, and the ECR image are available.

Parameter `InputBucketName`:

```text
<globally-unique-input-bucket-name>
```

Why: S3 bucket where notables are uploaded under `incoming/`.

Parameter `OutputBucketName`:

```text
<globally-unique-output-bucket-name>
```

Why: S3 bucket where markdown reports are written under `reports/`.

Parameter `SplunkSinkMode`:

```text
s3
```

Why: safest first deploy. Writes reports to S3 only.

Use this later only when Splunk REST writeback is ready:

```text
notable_rest
```

Parameter `CapabilityProfiles`:

```text
core
```

Why: selects the supported runtime capability bundle. Keep `core` for the
current S3/Lambda/Bedrock behavior. Later parity profiles such as `rag`,
`spl_readonly`, `elastic_readonly`, `ticket_draft`, and `action_gated` should be
enabled only after their operations guides and prerequisites are satisfied.

Parameter `AwsAccountId`:

```text
<12-digit-account-id>
```

Why: used to build the Bedrock inference profile ARN in `deploy/aws/template-sam.yaml`.

Find it with:

```bash
aws sts get-caller-identity --query Account --output text
```

Parameter `ImageUri`:

```text
<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:<tag>
```

Why: tells Lambda which already-pushed ECR image to run.

Find an existing repo URI with:

```bash
aws ecr describe-repositories \
  --repository-names <repo-name> \
  --region <region> \
  --query 'repositories[0].repositoryUri' \
  --output text
```

Parameter `InputRetentionDays`:

```text
2
```

Why: deletes uploaded input files after two days.

Parameter `OutputRetentionDays`:

```text
7
```

Why: deletes generated reports after seven days.

Parameter `MaxDecompressedInputBytes`:

```text
1048576
```

Why: caps the decompressed size of one gzip notable before Bedrock analysis. Increase only if the expected notable payloads require it.

Parameter `LambdaTimeoutSeconds`:

```text
360
```

Why: keeps the current core timeout. Use `900` as the starting point for
deployments that enable multiple Bedrock calls, Knowledge Base retrieval, or
external read-only investigation.

Parameter `LambdaMemorySize`:

```text
512
```

Why: keeps the current core memory allocation. Use `1024` as the starting point
for heavier parity profiles, then tune from CloudWatch duration and memory
evidence.

Parameter `LambdaEphemeralStorageMb`:

```text
512
```

Why: keeps the current Lambda ephemeral storage baseline. Increase only if a
future capability has measured local temporary-storage pressure.

Confirm changes before deploy:

```text
Y
```

Why: shows the CloudFormation change set before applying it.

Allow SAM CLI IAM role creation:

```text
Y
```

Why: the template creates Lambda execution permissions.

Disable rollback:

```text
N
```

Why: failed deploys should roll back by default.

Save arguments to configuration file:

```text
Y
```

Why: writes `samconfig.toml` so later deploys do not require all prompts again.

SAM configuration file:

```text
samconfig.toml
```

Why: default config file used by `sam deploy`.

SAM configuration environment:

```text
default
```

Why: default named environment inside `samconfig.toml`.

### After Deploy

Expected CloudFormation outputs:

- `FunctionArn`: deployed Lambda ARN.
- `InputBucketName`: bucket to upload test notables.
- `OutputBucketName`: bucket containing generated reports.
- `TestCommand`: sample `aws s3 cp` command for a test upload.

View outputs:

```bash
aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --region us-east-1 \
  --query 'Stacks[0].Outputs'
```

The current YAML does not build or publish the container image. Either build and push the image first, or update the SAM YAML so SAM builds and pushes it during deploy.
