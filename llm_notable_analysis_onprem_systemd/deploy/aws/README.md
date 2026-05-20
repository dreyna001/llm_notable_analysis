# AWS EC2 GPU Test Host (On-Prem Parity)

CloudFormation stack that provisions a **single RHEL 8 or 9 GPU EC2 instance**
and bootstraps the production-shaped on-prem chain:

`vLLM (gemma-4-31B-it) -> LiteLLM -> notable-analyzer -> file-drop smoke test`

This is for **lab / validation**, not a hardened production deployment.

## What the stack creates

- VPC, public subnet, security group (SSH only inbound)
- GPU EC2 instance on **official AWS Marketplace RHEL 8 or 9**
- Encrypted 500 GB gp3 root volume (configurable)
- IAM instance profile (SSM Session Manager + optional Secrets Manager read)
- Optional Hugging Face token in Secrets Manager
- systemd one-shot bootstrap that:
  1. Installs OS packages + Python (3.12 on RHEL 9; 3.12 or 3.11 on RHEL 8)
  2. Installs NVIDIA drivers (may reboot once)
  3. Clones your `llm_notable_analysis` monorepo
  4. Runs `scripts/install.sh` with `MODEL_DOWNLOAD=true`
  5. Runs `scripts/smoke_service_chain.sh`

## Prerequisites

| Item | Notes |
|------|-------|
| AWS account + CLI | `aws sts get-caller-identity` works |
| **RHEL Marketplace subscription** | Accept RHEL 8/9 in AWS Marketplace before first launch |
| EC2 key pair | For optional SSH (`ec2-user`) |
| GPU quota | `p5.4xlarge` (default) or similar in your region/AZ |
| Git URL | Must be the **full monorepo** (`llm_notable_analysis_onprem_systemd/` **and** `onprem_rag_notable_analysis/`) |
| Hugging Face token | Access to `google/gemma-4-31B-it`, unless you pre-stage weights |

## Deploy

RHEL 9 (default):

```bash
aws cloudformation deploy \
  --stack-name notable-analyzer-gpu-test \
  --template-file template-ec2-test.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    KeyPairName=your-key \
    RhelMajorVersion=9 \
    GitCloneUrl=https://github.com/your-org/llm_notable_analysis.git \
    GitBranch=main \
    HuggingFaceToken=hf_xxxxxxxx \
    AllowedSshCidr=203.0.113.10/32 \
    InstanceType=p5.4xlarge
```

RHEL 8:

```bash
  RhelMajorVersion=8 \
  ...
```

Use an existing HF secret instead of inline token:

```bash
  ExistingHuggingFaceTokenSecretArn=arn:aws:secretsmanager:us-east-1:123456789012:secret:hf-token-xxxxx
```

Override AMI explicitly (if Marketplace SSM lookup fails in your region):

```bash
  AmiId=ami-0123456789abcdef0
```

Default Marketplace AMI lookups:

| Version | SSM path |
|---------|----------|
| RHEL 9 | `/aws/service/marketplace/product/4ek98h08jp942/latest` |
| RHEL 8 | `/aws/service/marketplace/product/6bpmfw6729cq5/latest` |

## Monitor bootstrap

SSM (no SSH key required):

```bash
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name notable-analyzer-gpu-test \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" \
  --output text)

aws ssm start-session --target "$INSTANCE_ID"
```

On the host:

```bash
sudo tail -f /var/log/notable-analyzer-firstboot.log
sudo tail -f /var/log/notable-analyzer-bootstrap.log
sudo systemctl status notable-analyzer-bootstrap vllm litellm notable-analyzer
cat /etc/notable-analyzer/bootstrap-status.txt
```

Expect **30–90+ minutes** on first boot (driver reboot, pip installs, ~60 GB model download, vLLM load, smoke test).

## Verify manually

```bash
sudo bash /opt/llm-notable-analysis-src/llm_notable_analysis_onprem_systemd/scripts/smoke_service_chain.sh \
  --config-env /etc/notable-analyzer/config.env

# Drop a test notable
echo '{"notable_id":"manual-test","summary":"Test alert","ip_address":"203.0.113.45","user":"admin"}' \
  | sudo tee /var/notables/incoming/manual-test.json
ls -la /var/notables/reports/
```

## Instance sizing

Default `p5.4xlarge` = 1× H100 80 GB. The packaged `vllm.service` uses
`CUDA_VISIBLE_DEVICES=0` (single GPU).

If vLLM OOMs on load, reduce `--max-model-len` in `/etc/systemd/system/vllm.service`
for lab only, or use a larger GPU instance.

## Tear down

```bash
aws cloudformation delete-stack --stack-name notable-analyzer-gpu-test
```

Delete the stack when finished to stop GPU charges.

## Files

| File | Purpose |
|------|---------|
| `template-ec2-test.yaml` | CloudFormation stack |
| `bootstrap-ec2-test.sh` | Host bootstrap (cloned from repo on first boot) |
