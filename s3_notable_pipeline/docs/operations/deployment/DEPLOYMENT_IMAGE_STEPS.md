# Lambda Container Image and SAM Deployment

AWS SAM deploys `deploy/aws/template-sam.yaml` as a CloudFormation stack. The
template uses **image-based Lambda** (`PackageType: Image`) and does **not**
build, tag, or push the container image. You must publish an ECR image first, then
pass its URI as the `ImageUri` parameter (or use a SAM-managed build flow below).

## Image recipe

`deploy/docker/Dockerfile` (build context: `s3_notable_pipeline/`):

- **Base:** replace the placeholder `FROM` with an approved Lambda **Python 3.12**
  base you can pull (example placeholder:
  `<account>.dkr.ecr.us-east-1.amazonaws.com/ironbank/lambda.python:312`).
- **Install:** `requirements.txt` via `pip`.
- **Copy:** `src/s3_notable_pipeline` into `${LAMBDA_TASK_ROOT}/s3_notable_pipeline`.
- **Default CMD:** `s3_notable_pipeline.lambda_handler.handler`.

## One image, three entrypoints

All image-based functions in `template-sam.yaml` share the **same** `ImageUri`.
SAM sets handler overrides where needed:

| Function (default name) | When deployed | Entry command |
| --- | --- | --- |
| `notable-analyzer-s3` | Always | Dockerfile `CMD` (`lambda_handler.handler`) |
| `notable-case-embed` | `CaseIndexTableName` non-empty | `s3_notable_pipeline.embed_handler.handler` |
| `notable-portal-api` | `CaseIndexTableName` non-empty | `s3_notable_pipeline.portal_handler.handler` |

Build and push **one** image; all three functions reference it.

## ECR URI format

```text
<account-id>.dkr.ecr.<region>.amazonaws.com/<repo-name>:<tag>
```

Template default (replace account and tag):

```text
123456789012.dkr.ecr.us-east-1.amazonaws.com/notable-analyzer-s3:latest
```

Look up values:

```bash
aws sts get-caller-identity --query Account --output text
aws configure get region
aws ecr describe-repositories --region us-east-1
aws ecr describe-repositories --repository-names notable-analyzer-s3 \
  --region us-east-1 --query 'repositories[0].repositoryUri' --output text
```

## Required order (manual build and push)

Run from `s3_notable_pipeline/` after fixing the Dockerfile `FROM` line.

**Region note:** the template hard-codes the Bedrock inference profile ARN to
`us-east-1`. Use `us-east-1` for Lambda, ECR, and Bedrock unless you also update
`deploy/aws/template-sam.yaml` and IAM for another region.

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=<12-digit-account-id>
export IMAGE_REPO=notable-analyzer-s3
export IMAGE_TAG=latest
export IMAGE_URI=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_REPO:$IMAGE_TAG
```

```bash
# Skip if the repository already exists
aws ecr create-repository --repository-name $IMAGE_REPO --region $AWS_REGION

aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com

docker build -f deploy/docker/Dockerfile -t $IMAGE_REPO:$IMAGE_TAG .
docker tag $IMAGE_REPO:$IMAGE_TAG $IMAGE_URI
docker push $IMAGE_URI
```

Use immutable tags (build id, date, git SHA) in customer environments instead of
`latest` when that matches org policy.

## SAM build and deploy

`sam build` with the current template prepares `.aws-sam/build/template.yaml` but
does **not** create the ECR image when `ImageUri` points at an existing registry
URI.

```bash
sam build -t deploy/aws/template-sam.yaml
```

**Fast path (after image is in ECR):**

```powershell
.\scripts\setup-and-deploy.ps1
```

```bash
chmod +x ./scripts/setup-and-deploy.sh
./scripts/setup-and-deploy.sh
```

Both scripts validate AWS CLI, SAM CLI, and Docker; check Bedrock access for
Claude Sonnet 4.6 inference profiles; run `sam build`; then `sam deploy` using
`samconfig.toml` when present, otherwise `sam deploy --guided`. They do **not**
run `docker build` or `docker push`.

**First guided deploy** (no `samconfig.toml`):

```bash
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

Minimum prompts for a safe first stack:

- `SplunkSinkMode=s3`
- Globally unique `InputBucketName` and `OutputBucketName`
- `CapabilityProfiles=core`
- `AwsAccountId` (required; no template default)
- `ImageUri` = the URI you pushed above
- `MaxDecompressedInputBytes=1048576` unless larger gzip payloads are expected

**Repeat deploy** with saved config:

```bash
sam deploy --template-file .aws-sam/build/template.yaml
```

**Explicit parameter overrides:**

```bash
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name notable-analyzer-stack \
  --region $AWS_REGION \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    InputBucketName=<globally-unique-input-bucket> \
    OutputBucketName=<globally-unique-output-bucket> \
    SplunkSinkMode=s3 \
    CapabilityProfiles=core \
    AwsAccountId=$AWS_ACCOUNT_ID \
    ImageUri=$IMAGE_URI
```

Or pass only `ImageUri` when other values live in `samconfig.toml`:

```bash
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --parameter-overrides AwsAccountId=$AWS_ACCOUNT_ID ImageUri=$IMAGE_URI
```

## Key template parameters (deploy time)

| Parameter | Default | Notes |
| --- | --- | --- |
| `ImageUri` | placeholder ECR URI | Must exist in ECR before deploy |
| `AwsAccountId` | *(required)* | Builds Bedrock inference profile ARN |
| `SplunkSinkMode` | `s3` | Use `notable_rest` only with Splunk REST ready |
| `CapabilityProfiles` | `core` | See capability guide before enabling parity profiles |
| `LambdaTimeoutSeconds` | `360` | Start at `900` for heavier profiles |
| `LambdaMemorySize` | `512` | Start at `1024` for heavier profiles |
| `LambdaReservedConcurrentExecutions` | `5` | Caps concurrent Lambda executions |
| `MaxDecompressedInputBytes` | `1048576` | Gzip-only; rejects oversized decompressed payloads |
| `InputRetentionDays` / `OutputRetentionDays` | `2` / `7` | S3 lifecycle under `incoming/` / `reports/` |
| `CaseIndexTableName` | *(empty)* | Non-empty enables embed + portal Lambdas on the same image |

For `notable_rest`, also set `SplunkBaseUrl` and a real `SplunkApiTokenSecretArn`
(not `*`). See integrations guides before enabling writeback.

## Alternative: SAM-managed image build

To have SAM build from `deploy/docker/Dockerfile` instead of a pre-pushed URI,
remove the `ImageUri` parameter usage and add `Metadata` on each
`PackageType: Image` function (same Dockerfile/context). Example for the analyzer:

```yaml
NotableAnalyzerFunction:
  Type: AWS::Serverless::Function
  Properties:
    FunctionName: notable-analyzer-s3
    PackageType: Image
    Timeout: !Ref LambdaTimeoutSeconds
    MemorySize: !Ref LambdaMemorySize
  Metadata:
    Dockerfile: deploy/docker/Dockerfile
    DockerContext: .
    DockerTag: latest
```

Apply equivalent `Metadata` to `CaseEmbedFunction` and `PortalApiFunction`
(keep their `ImageConfig.Command` overrides). Then:

```bash
sam build -t deploy/aws/template-sam.yaml
sam deploy --guided --template-file .aws-sam/build/template.yaml
```

Non-guided push to an existing repo:

```bash
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --image-repository $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$IMAGE_REPO
```

The Dockerfile `FROM` image must still be real and pullable.

## After deploy

CloudFormation outputs (always): `FunctionArn`, `InputBucketName`,
`OutputBucketName`, `TestCommand`.

When `CaseIndexTableName` is set, also check `PortalApiUrl` and related portal
outputs. When the portal UI bucket is configured, use `PortalUiDistributionDomainName`.

```bash
aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --region us-east-1 \
  --query 'Stacks[0].Outputs'
```

Smoke test:

```powershell
.\scripts\test-pipeline.ps1
```

If Lambda fails with `not authorized to perform: bedrock:InvokeModel`, confirm
the execution role allows `bedrock:InvokeModel` on the same inference profile ARN
as `BEDROCK_MODEL_ID` (`us.anthropic.claude-sonnet-4-6` in `us-east-1`).

## Related Docs

- [`../../../README.md`](../../../README.md) — fast-path deploy and test scripts
- [`../../../deploy/aws/template-sam.yaml`](../../../deploy/aws/template-sam.yaml) — infrastructure contract
- [`../../../deploy/docker/Dockerfile`](../../../deploy/docker/Dockerfile) — Lambda image recipe
- [`../../../scripts/setup-and-deploy.sh`](../../../scripts/setup-and-deploy.sh) — automated SAM build/deploy
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) — `CapabilityProfiles` bundles
- [`../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) — S3 intake, gzip limits, retention
- [`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md) — Bedrock model, timeout, memory tuning
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md) — IAM, secrets, endpoint validation
- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) — portal stack when `CaseIndexTableName` is set
- [`../integrations/SPLUNK_WRITEBACK_OPERATIONS.md`](../integrations/SPLUNK_WRITEBACK_OPERATIONS.md) — `SplunkSinkMode=notable_rest`
- [`../../testing/TESTING.md`](../../testing/TESTING.md) — unit, smoke, and integration tests
