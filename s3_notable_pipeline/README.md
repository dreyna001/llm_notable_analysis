# AWS Deployment Guide - S3 Notable Pipeline

Complete step-by-step guide to deploy the S3-triggered notable analysis pipeline to AWS.

## Architecture Overview

```
S3 Input Bucket (incoming/) → Lambda Function → AWS Bedrock Nova Pro → Output
                                                      ↓
                                    S3 (test) / Splunk HEC / Splunk REST
```

### Visualize `architecture.mmd` (Mermaid)

You can view the diagram directly in editors that support Mermaid (e.g., VS Code Mermaid preview). If you want a deterministic SVG/PNG/PDF render locally, this folder includes a small Node-based renderer setup.

#### Prereqs

- Node.js + npm

Verify:

```bash
node --version
npm --version
```

#### Install renderer deps (one-time)

```bash
cd s3_notable_pipeline
npm install
```

#### Render outputs

```bash
cd s3_notable_pipeline
npm run render:svg
npm run render:png
npm run render:pdf
```

Outputs are generated next to the source diagram:
- `architecture.svg`
- `architecture.png`
- `architecture.pdf`

### TODO report (prompt/input schema, etc.)

This folder uses in-code TODO/FIXME markers (for example, a TODO to revisit the prompt/input format once the Splunk alert schema is finalized).

Generate/update the consolidated report:

```bash
cd s3_notable_pipeline
python tools/todo_report.py --write
```

Or via npm:

```bash
cd s3_notable_pipeline
npm run todos
```

The generated file is `s3_notable_pipeline/TODOS.md`.

**What this pipeline does:**
- Automatically processes security notables uploaded to S3
- Analyzes them using AWS Bedrock for MITRE ATT&CK TTP identification
- Outputs analysis results to S3 (test mode) or Splunk (production mode)
- No UI - pure backend workflow triggered by S3 events

**Key Features:**
- Event-driven, parallel processing (each S3 object triggers a separate Lambda invocation)
- Three output modes: S3 (test), Splunk HEC, or Splunk REST API
- Scales automatically with notable volume
- Automatic cleanup: Input notables and output reports are ephemeral, auto-deleted after configurable retention periods (default: 2 days for input, 7 days for output)

---

## Installation Requirements

You need the following tools installed **locally** on your machine before deploying:

### 1. AWS CLI

**Windows (PowerShell):**
```powershell
# Option 1: Via winget
winget install Amazon.AWSCLI

# Option 2: Download MSI installer
# Visit: https://aws.amazon.com/cli/
```

**macOS:**
```bash
brew install awscli
```

**Linux:**
```bash
# Follow instructions at: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
```

**Verify installation:**
```bash
aws --version
```

**Configure credentials:**
```bash
aws configure
# You'll need: AWS Access Key ID, Secret Access Key, Region, Output format
```

### 2. AWS SAM CLI

**Windows (PowerShell):**
```powershell
# Option 1: Via Chocolatey
choco install aws-sam-cli

# Option 2: Download installer
# Visit: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
```

**macOS:**
```bash
brew install aws-sam-cli
```

**Linux:**
```bash
# Follow instructions at: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html
```

**Verify installation:**
```bash
sam --version
```

### 3. Docker

**Why you need it:** This pipeline uses Lambda container images (not zip packages). SAM CLI builds a Docker image locally during `sam build`.

**Windows:**
- Download Docker Desktop: https://www.docker.com/products/docker-desktop/
- Install and start Docker Desktop
- Ensure WSL 2 backend is enabled (recommended)

**macOS:**
```bash
brew install --cask docker
# Or download Docker Desktop from: https://www.docker.com/products/docker-desktop/
```

**Linux:**
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group (to run without sudo)
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect
```

**Verify installation:**
```bash
docker --version
docker ps  # Should show running containers (or empty list if none running)
```

### 4. Verify All Prerequisites

```bash
# Check AWS CLI
aws sts get-caller-identity

# Check SAM CLI
sam --version

# Check Docker
docker --version
docker ps

# Check Bedrock access
aws bedrock list-foundation-models --region us-east-1
```

**Important:** Docker must be running when you execute `sam build`. SAM CLI builds the Lambda container image locally using Docker, then pushes it to Amazon ECR during deployment.

---

## Pipeline Files

**Core Code Files:**
- `lambda_handler.py` - Main Lambda entrypoint with S3 event handling and sink routing
- `ttp_analyzer.py` - Bedrock-based TTP analysis
- `markdown_generator.py` - Report generation
- `enterprise_attack_v17.1_ids.json` - MITRE ATT&CK data
- `requirements.txt` - Python dependencies (requests only; boto3 included in base image)
- `Dockerfile` - Container image definition for Lambda

### Lambda naming vs runtime handler (important)

- **`FunctionName` in `template-sam.yaml`** (e.g., `notable-analyzer-s3`) is just the **deployed Lambda resource name**.
- **What must match for execution** is the container handler entrypoint in `Dockerfile`:
  - `CMD ["lambda_handler.handler"]` means `lambda_handler.py` must export `def handler(event, context):`.
- **If you change `FunctionName`**, also update any IAM resources that hardcode it (notably the CloudWatch Logs ARN that references `/aws/lambda/<FunctionName>:*`), otherwise log writes can fail.

**Infrastructure Templates:**
- `template-sam.yaml` - AWS SAM template for deployment (recommended)
- `template-cfn.yaml` - Pure CloudFormation template (alternative)

---

## Output Modes

### Test Mode (`SPLUNK_SINK_MODE=s3`)
- **Use case:** Testing and development without Splunk
- **Input:** Upload notables (JSON or text) to `s3://<input-bucket>/incoming/`
- **Output:** Markdown reports written to `s3://<output-bucket>/reports/` (one `.md` file per input)
- **Required env vars:** `OUTPUT_BUCKET_NAME`

### Production Mode - HEC (`SPLUNK_SINK_MODE=hec`)
- **Use case:** Send analysis results to Splunk as new events
- **Input:** Notables from S3 (written by Splunk ES S3 app)
- **Output:** POST to Splunk HTTP Event Collector with full analysis (markdown + structured TTP data)
- **Required env vars:** `SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN`

### Production Mode - REST (`SPLUNK_SINK_MODE=notable_rest`)
- **Use case:** Update existing notable comments with full analysis
- **Input:** Notables from S3 (must include `notable_id` or `search_name`)
- **Output:** Update notable comment via `/services/notable_update` REST API with full markdown report
- **Required env vars:** `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`

---

## Deployment Method 1: AWS SAM (Recommended - Easiest)

### Step 1: Navigate to Pipeline Directory

```bash
cd s3_notable_pipeline
```

### Step 2: Build the Application

**Note:** This pipeline uses a Lambda container image (not a zip package), which bypasses the 250 MB deployment size limit. Docker must be installed and running on your machine.

```bash
sam build -t template-sam.yaml
```

**What happens during `sam build`:**
1. SAM reads `template-sam.yaml` and finds the `NotableAnalyzerFunction` resource with `PackageType: Image`
2. Builds a Docker image using the `Dockerfile` in the project directory
3. Base image: `public.ecr.aws/lambda/python:3.12` (includes boto3 and Lambda runtime)
4. Installs dependencies from `requirements.txt` (`requests==2.32.5`) into the image
5. Copies your code files: `lambda_handler.py`, `ttp_analyzer.py`, `markdown_generator.py`, `enterprise_attack_v17.1_ids.json`
6. Creates a Lambda-compatible container image (size limit: 10 GB)

**Prerequisites:**
- Docker must be installed and running
- Docker Desktop (Windows/Mac) or Docker Engine (Linux)
- Verify: `docker --version`

**Note:** The image is built locally, then pushed to Amazon ECR during `sam deploy`.

### Step 3: Deploy (Guided Mode - First Time)

```bash
sam deploy --guided
```

**You'll be prompted for the following:**

1. **Stack Name:** `notable-analyzer-stack` (or your preferred name)
2. **AWS Region:** `us-east-1` (or your preferred region - ensure Bedrock is available)
3. **Parameter InputBucketName:** `my-notables-input` (or your preferred bucket name)
4. **Parameter OutputBucketName:** `my-notables-output` (or your preferred bucket name)
5. **Parameter SplunkSinkMode:** `s3` (for testing - options: `s3`, `hec`, `notable_rest`)
6. **Parameter SplunkHecUrl:** (leave blank for test mode)
7. **Parameter SplunkHecToken:** (leave blank for test mode)
8. **Parameter SplunkBaseUrl:** (leave blank for test mode)
9. **Parameter SplunkApiToken:** (leave blank for test mode)
10. **Parameter InputRetentionDays:** `2` (default - days to keep input files)
11. **Parameter OutputRetentionDays:** `7` (default - days to keep output reports)
12. **Confirm changes before deploy:** `Y` (recommended)
13. **Allow SAM CLI IAM role creation:** `Y` (required for Lambda permissions)
14. **Disable rollback:** `N` (keep default)
15. **Save arguments to configuration file:** `Y` (saves to `samconfig.toml` for future deployments)

**Note:** Bucket names must be globally unique across all AWS accounts.

**What happens during `sam deploy`:**
1. SAM creates an Amazon ECR repository (if it doesn't exist) for your Lambda container image
2. Pushes the built Docker image to ECR
3. Creates/updates the CloudFormation stack using `template-sam.yaml`
4. Lambda function references the ECR image URI and pulls it on first invocation

**Note:** The ECR repository is kept (not deleted) for future deployments and rollbacks. Container images are versioned by tag.

### Step 4: Deploy (Non-Interactive Mode - Subsequent Deployments)

After the first deployment, you can use the saved configuration:

```bash
sam deploy
```

Or specify parameters explicitly:

```bash
sam deploy \
  --stack-name notable-analyzer-stack \
  --parameter-overrides \
    InputBucketName=my-notables-input \
    OutputBucketName=my-notables-output \
    SplunkSinkMode=s3 \
    InputRetentionDays=2 \
    OutputRetentionDays=7 \
  --capabilities CAPABILITY_NAMED_IAM \
  --resolve-s3
```

### Step 5: Configure Splunk Environment Variables (Optional - Manual)

**Note:** The Splunk environment variables (`SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN`, `SPLUNK_BASE_URL`, `SPLUNK_API_TOKEN`) are not created during deployment. Add them manually when you're ready to use Splunk integration.

**Option A: AWS Console**
1. Go to **Lambda** → **notable-analyzer-s3** → **Configuration** → **Environment variables**
2. Click **Edit**
3. Click **Add environment variable** for each:
   - `SPLUNK_HEC_URL` = `https://your-splunk:8088/services/collector/event` (if using HEC mode)
   - `SPLUNK_HEC_TOKEN` = `your-hec-token` (if using HEC mode)
   - `SPLUNK_BASE_URL` = `https://your-splunk:8089` (if using REST mode)
   - `SPLUNK_API_TOKEN` = `your-api-token` (if using REST mode)
4. Click **Save**

**Option B: AWS CLI**
```bash
# Update Lambda function with Splunk environment variables
aws lambda update-function-configuration \
  --function-name notable-analyzer-s3 \
  --environment "Variables={
    BEDROCK_MODEL_ID=amazon.nova-pro-v1:0,
    SPLUNK_SINK_MODE=hec,
    INPUT_BUCKET_NAME=your-input-bucket,
    OUTPUT_BUCKET_NAME=your-output-bucket,
    OUTPUT_PREFIX=reports,
    SPLUNK_HEC_URL=https://your-splunk:8088/services/collector/event,
    SPLUNK_HEC_TOKEN=your-hec-token,
    SPLUNK_BASE_URL=https://your-splunk:8089,
    SPLUNK_API_TOKEN=your-api-token
  }"
```

**Verify environment variables:**
```bash
aws lambda get-function-configuration \
  --function-name notable-analyzer-s3 \
  --query 'Environment.Variables'
```

**Important:** If you update the CloudFormation stack later, manually added environment variables may be overwritten. Consider updating stack parameters instead for production use.

### Step 6: Verify Deployment

```bash
# Check stack status
aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --query 'Stacks[0].StackStatus'

# Get stack outputs (bucket names, function ARN)
aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --query 'Stacks[0].Outputs'
```

---

## Deployment Method 2: CloudFormation (Manual)

Use this method if you don't have SAM CLI or prefer manual control.

### Step 1: Package Lambda Code

```bash
cd s3_notable_pipeline

# Create package directory for dependencies
mkdir -p package

# Install Python dependencies
pip install --target ./package -r requirements.txt

# Create deployment zip with dependencies
cd package
zip -r ../lambda-package.zip .

# Add your code files
cd ..
zip -r lambda-package.zip \
  lambda_handler.py \
  ttp_analyzer.py \
  markdown_generator.py \
  enterprise_attack_v17.1_ids.json
```

### Step 2: Upload Package to S3

```bash
# Create a deployment bucket (if you don't have one)
aws s3 mb s3://my-lambda-deployment-bucket --region us-east-1

# Upload the Lambda package
aws s3 cp lambda-package.zip s3://my-lambda-deployment-bucket/lambda-package.zip
```

### Step 3: Deploy CloudFormation Stack

```bash
aws cloudformation create-stack \
  --stack-name notable-analyzer-stack-cfn \
  --template-body file://template-cfn.yaml \
  --parameters \
    ParameterKey=InputBucketName,ParameterValue=my-notables-input \
    ParameterKey=OutputBucketName,ParameterValue=my-notables-output \
    ParameterKey=SplunkSinkMode,ParameterValue=s3 \
    ParameterKey=InputRetentionDays,ParameterValue=2 \
    ParameterKey=OutputRetentionDays,ParameterValue=7 \
    ParameterKey=LambdaCodeS3Bucket,ParameterValue=my-lambda-deployment-bucket \
    ParameterKey=LambdaCodeS3Key,ParameterValue=lambda-package.zip \
  --capabilities CAPABILITY_NAMED_IAM \
  --region us-east-1
```

### Step 4: Monitor Stack Creation

```bash
# Watch stack creation progress
aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack-cfn \
  --query 'Stacks[0].StackStatus'

# Wait for CREATE_COMPLETE status
```

---

## Testing the Deployment

### Test 1: Create Test Notable File

```bash
cat > test-notable.txt << EOF
Suspicious PowerShell execution detected on host WIN-SERVER-01.
Command: powershell.exe -EncodedCommand <base64>
User: DOMAIN\admin
Time: 2024-11-25T14:30:00Z
Source IP: 192.168.1.100
Destination: external-server.com
EOF
```

### Test 2: Upload to Input Bucket

```bash
# Get input bucket name from stack outputs
export INPUT_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --query 'Stacks[0].Outputs[?OutputKey==`InputBucketName`].OutputValue' \
  --output text)

# Upload test file (must be in 'incoming/' prefix)
aws s3 cp test-notable.txt s3://$INPUT_BUCKET/incoming/test-notable.txt
```

### Test 3: Wait and Check Output

Wait 30-60 seconds for Lambda to process, then:

```bash
# Get output bucket name
export OUTPUT_BUCKET=$(aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --query 'Stacks[0].Outputs[?OutputKey==`OutputBucketName`].OutputValue' \
  --output text)

# List output files
aws s3 ls s3://$OUTPUT_BUCKET/reports/

# Download markdown report
aws s3 cp s3://$OUTPUT_BUCKET/reports/test-notable.md ./

# View the markdown report
cat test-notable.md
```

### Test 4: Check Lambda Logs

```bash
# Get Lambda function name
export LAMBDA_NAME=$(aws cloudformation describe-stacks \
  --stack-name notable-analyzer-stack \
  --query 'Stacks[0].Outputs[?OutputKey==`FunctionArn`].OutputValue' \
  --output text | cut -d: -f7)

# View recent logs
aws logs tail /aws/lambda/$LAMBDA_NAME --follow

# Or view in CloudWatch Console
# https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups
```

### Test with Splunk HEC

1. **Update the stack with HEC credentials:**
   ```bash
   sam deploy \
     --parameter-overrides \
       SplunkSinkMode=hec \
       SplunkHecUrl=https://your-splunk:8088/services/collector/event \
       SplunkHecToken=your-hec-token
   ```

2. **Upload a notable and verify it appears in Splunk:**
   ```bash
   aws s3 cp test-notable.txt s3://$INPUT_BUCKET/incoming/test-notable.txt
   ```

3. **Search in Splunk:**
   ```
   index=* sourcetype="notable:analysis"
   ```

---

## Configuration Options

### Template Parameters

#### Retention Settings
- `InputRetentionDays` - Days to retain input notables before auto-deletion (default: `2`, range: 1-365)
  - **Purpose:** Controls storage costs by automatically expiring processed notables
  - **Recommendation:** Keep at 2+ days to ensure Lambda has time to process during outages/backlogs
  - **Change via:** SAM deploy parameters or CloudFormation console
- `OutputRetentionDays` - Days to retain output reports before auto-deletion (default: `7`, range: 1-365)
  - **Purpose:** Keeps markdown reports temporarily for review without long-term storage costs
  - **Recommendation:** Adjust based on how long you need reports accessible in S3

**Note:** S3 lifecycle rules delete objects based on age, not per-write. New notables are processed immediately by Lambda (event-driven) and only deleted days later when they reach the retention threshold.

### Environment Variables

#### Core Configuration
- `BEDROCK_MODEL_ID` - Bedrock model to use (default: `amazon.nova-pro-v1:0`)
- `SPLUNK_SINK_MODE` - Output mode: `s3`, `hec`, or `notable_rest` (default: `s3`)
- `INPUT_BUCKET_NAME` - S3 bucket for input notables
- `OUTPUT_PREFIX` - S3 prefix for output files (default: `reports`)

#### S3 Sink (Test Mode)
- `OUTPUT_BUCKET_NAME` - S3 bucket for markdown output (required for `s3` mode)

#### Splunk HEC Sink
- `SPLUNK_HEC_URL` - Full HEC endpoint URL (e.g., `https://splunk:8088/services/collector/event`)
- `SPLUNK_HEC_TOKEN` - HEC authentication token

#### Splunk REST Sink
- `SPLUNK_BASE_URL` - Splunk base URL (e.g., `https://splunk:8089`)
- `SPLUNK_API_TOKEN` - API token for REST authentication

---

## Retention & Storage Management

**S3 lifecycle rules handle cleanup automatically:**
- **Input notables** (`incoming/` prefix): Auto-deleted after `InputRetentionDays` (default: 2 days)
- **Output reports** (`reports/` prefix): Auto-deleted after `OutputRetentionDays` (default: 7 days)

**Why this works:**
- Lambda processes notables immediately on upload (event-driven), long before lifecycle expiration
- Lifecycle rules run as periodic background jobs and only delete objects older than the configured retention
- Storage costs stay bounded without manual cleanup or extra code

**Adjusting retention:**
- **SAM:** Pass `--parameter-overrides InputRetentionDays=3 OutputRetentionDays=14` to `sam deploy`
- **CloudFormation:** Update parameters in the console or CLI
- **Recommendation:** Keep `InputRetentionDays` at 2+ days to handle backlogs/outages safely

**For compliance-grade archiving:** Configure Splunk or a separate S3 bucket without lifecycle expiration to retain notables/reports long-term.

---

## Switching to Production (Splunk Integration)

### Option A: Switch to Splunk HEC

```bash
sam deploy \
  --stack-name notable-analyzer-stack \
  --parameter-overrides \
    SplunkSinkMode=hec \
    SplunkHecUrl=https://your-splunk-server:8088/services/collector/event \
    SplunkHecToken=your-hec-token-here
```

**No code changes required** - the same Lambda handles all modes.

### Option B: Switch to Splunk REST API

```bash
sam deploy \
  --stack-name notable-analyzer-stack \
  --parameter-overrides \
    SplunkSinkMode=notable_rest \
    SplunkBaseUrl=https://your-splunk-server:8089 \
    SplunkApiToken=your-api-token-here
```

**Important:** Ensure your notables include `notable_id` or `search_name` fields when using REST mode.

---

## Key Design Decisions

1. **Three sink modes:** Single Lambda supports S3 (test), Splunk HEC (full analysis as new event), and Splunk REST (full markdown as notable comment) via `SPLUNK_SINK_MODE` env var.

2. **Event-driven concurrency:** Each S3 object triggers a separate Lambda invocation, so notables process in parallel automatically.

3. **No VPC by default:** Lambda runs without VPC for simplicity. Add VPC config if Splunk is on-premises.

4. **Secrets as parameters:** Splunk credentials are CloudFormation parameters (use Secrets Manager in production).

5. **Automatic cleanup via S3 lifecycle:** Input notables and output reports are ephemeral, auto-deleted after configurable retention periods to control storage costs without extra Lambda logic.

---

## Monitoring and Troubleshooting

### View Lambda Logs

```bash
# Follow logs in real-time
aws logs tail /aws/lambda/notable-analyzer-s3 --follow

# View last 100 log entries
aws logs tail /aws/lambda/notable-analyzer-s3 --since 1h
```

### Common Issues

**Lambda not triggering:**
- Verify file is uploaded to `incoming/` prefix (not root of bucket)
- Check S3 event notification is configured: `aws s3api get-bucket-notification-configuration --bucket <input-bucket>`
- Verify Lambda permissions allow S3 to invoke it

**Bedrock access denied:**
- Check Lambda execution role has `bedrock:InvokeModel` permission
- Verify Bedrock is available in your region: `aws bedrock list-foundation-models --region <region>`
- Ensure model ID is correct: `amazon.nova-pro-v1:0`

**S3 output not appearing:**
- Verify `OUTPUT_BUCKET_NAME` environment variable is set
- Check Lambda has write permissions to output bucket
- Review CloudWatch Logs for errors
- Ensure file was uploaded to `incoming/` prefix (Lambda only processes files in this prefix)

**Splunk HEC errors:**
- Verify HEC URL is correct and accessible from Lambda
- Check HEC token is valid
- Ensure HEC endpoint accepts the `notable:analysis` sourcetype

**Splunk REST errors:**
- Verify REST API URL and token
- Check notables include `notable_id` or `search_name`
- Ensure Lambda can reach Splunk (VPC/network config)

### CloudWatch Metrics

Monitor these metrics in CloudWatch:
- Lambda invocations
- Lambda errors
- Lambda duration
- Bedrock API calls (via CloudTrail)

---

## Updating the Deployment

### Update Lambda Code

```bash
# Make your code changes, then:

# SAM method
sam build
sam deploy

# CloudFormation method
# Re-package and upload (see Step 1-2 of CloudFormation method)
# Then update stack:
aws cloudformation update-stack \
  --stack-name notable-analyzer-stack-cfn \
  --template-body file://template-cfn.yaml \
  --parameters ... (same as create-stack)
```

### Update Configuration

```bash
# Change any parameter (e.g., retention days)
sam deploy \
  --parameter-overrides \
    InputRetentionDays=5 \
    OutputRetentionDays=14
```

---

## Cost Estimate

**For 200-250 notables per day:**

- **Lambda invocations:** 250/day × 30 days = 7,500/month (within free tier)
- **Lambda compute:** ~60 seconds/invocation × 512 MB = ~$0.50/month
- **S3 storage:** ~1 MB/notable × 7,500 = 7.5 GB = ~$0.18/month
- **Bedrock Nova Pro:** 250/day × $0.0003 = ~$2.25/month
- **CloudWatch Logs:** ~$0.50/month (log ingestion and storage)

**Total: ~$3.50/month**

**Note:** Costs scale linearly with notable volume. Bedrock is the primary cost driver.

---

## Security Considerations

1. **IAM Permissions:** Lambda execution role uses least privilege (only S3 read, S3 write, Bedrock invoke)
2. **S3 Bucket Policies:** Input bucket should restrict write access to authorized sources (e.g., Splunk ES)
3. **Secrets Management:** For production, use AWS Secrets Manager instead of CloudFormation parameters for Splunk credentials
4. **VPC Configuration:** If Splunk is on-premises, deploy Lambda in a VPC with appropriate network configuration
5. **Encryption:** Enable S3 bucket encryption and Lambda environment variable encryption
6. **CloudTrail:** Enable CloudTrail to audit Bedrock API calls
7. **No public endpoints:** Lambda is triggered by S3 events only
8. **IAM-based auth:** All AWS service calls use IAM roles

---

## Cleanup

### Delete the Stack

**SAM method:**
```bash
sam delete --stack-name notable-analyzer-stack
```

**CloudFormation method:**
```bash
aws cloudformation delete-stack --stack-name notable-analyzer-stack-cfn
```

**Note:** S3 buckets are NOT automatically deleted. Manually empty and delete them:

```bash
# Empty buckets first
aws s3 rm s3://my-notables-input --recursive
aws s3 rm s3://my-notables-output --recursive

# Delete buckets
aws s3 rb s3://my-notables-input
aws s3 rb s3://my-notables-output
```

---

## Next Steps

1. **Test thoroughly** with various notable types
2. **Set up CloudWatch alarms** for Lambda errors and Bedrock throttling
3. **Configure Splunk integration** when ready for production
4. **Review retention settings** based on your compliance needs
5. **Set up monitoring dashboard** in CloudWatch
6. **Document your deployment** for your team

---

## Support Resources

- **Template files:** `template-sam.yaml`, `template-cfn.yaml`
- **Code documentation:** See inline comments in `lambda_handler.py`, `ttp_analyzer.py`, `markdown_generator.py`
- **AWS SAM documentation:** https://docs.aws.amazon.com/serverless-application-model/
- **Lambda documentation:** https://docs.aws.amazon.com/lambda/
- **Bedrock documentation:** https://docs.aws.amazon.com/bedrock/
