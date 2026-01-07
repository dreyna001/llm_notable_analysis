# ECS Frontend Deployment Guide

## Overview

This directory contains everything needed to containerize and deploy the Notable Analysis frontend to AWS ECS.

## Architecture

```
User Browser
    ↓
ECS Service (ALB)
    ↓
Container (nginx:80 + Python backend:8080)
    ↓
Amazon Bedrock (Nova Pro)
```

## Files

- `index.html`, `main.js`, `styles.css` - Static frontend (served by nginx)
- `backend.py` - Flask app that calls Bedrock directly
- `ttp_analyzer.py` - TTP analysis logic
- `markdown_generator.py` - Report generation
- `enterprise_attack_v17.1_ids.json` - MITRE ATT&CK data
- `Dockerfile` - Build for nginx + backend
- `nginx.conf` - Nginx config (proxies /api/* to backend)
- `supervisord.conf` - Runs both nginx and backend in one container
- `backend_requirements.txt` - Python dependencies for backend

## Prerequisites

1. Docker installed locally
2. AWS CLI configured
3. ECR repository created
4. Bedrock access enabled in your AWS account

## Step 1: Build and Test Locally

```bash
# Build image
docker build -t notable-frontend .

# Run locally (won't work without AWS credentials)
docker run -p 8080:80 notable-frontend

# Test with AWS credentials
docker run -p 8080:80 \
  -e AWS_ACCESS_KEY_ID=xxx \
  -e AWS_SECRET_ACCESS_KEY=xxx \
  -e AWS_REGION=us-east-1 \
  notable-frontend
```

Open http://localhost:8080

## Step 3: Push to ECR

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com

# Tag image
docker tag notable-frontend:latest \
  YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/notable-frontend:latest

# Push
docker push YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/notable-frontend:latest
```

## Step 4: Create ECS Task Definition

Create `task-definition.json`:

```json
{
  "family": "notable-frontend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::YOUR_ACCOUNT:role/NotableFrontendTaskRole",
  "containerDefinitions": [
    {
      "name": "notable-frontend",
      "image": "YOUR_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/notable-frontend:latest",
      "portMappings": [
        {
          "containerPort": 80,
          "protocol": "tcp"
        }
      ],
      "essential": true,
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/notable-frontend",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      }
    }
  ]
}
```

Register:
```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

## Step 5: Create ECS Task Role

The task role needs permission to invoke Bedrock:

```bash
# Create trust policy
cat > task-trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "ecs-tasks.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create role
aws iam create-role \
  --role-name NotableFrontendTaskRole \
  --assume-role-policy-document file://task-trust-policy.json

# Attach Bedrock invoke policy
cat > bedrock-invoke-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0"
    }
  ]
}
EOF

aws iam put-role-policy \
  --role-name NotableFrontendTaskRole \
  --policy-name BedrockInvokePolicy \
  --policy-document file://bedrock-invoke-policy.json
```

## Step 6: Create ECS Service

```bash
aws ecs create-service \
  --cluster your-cluster-name \
  --service-name notable-frontend \
  --task-definition notable-frontend \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxx],securityGroups=[sg-xxx],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=notable-frontend,containerPort=80"
```

## Step 7: Configure ALB

1. Create target group (HTTP:80, health check: `/health`)
2. Create ALB listener (HTTP:80 or HTTPS:443)
3. Point listener to target group
4. Update security groups to allow traffic

## Security Considerations

- **No public APIs**: All calls use IAM roles, not public URLs
- **ALB can be internal**: Set `scheme=internal` for VPC-only access
- **Add WAF**: Attach AWS WAF to ALB for additional protection
- **Use HTTPS**: Add ACM certificate to ALB listener
- **Restrict task role**: Only grant `bedrock:InvokeModel` on specific model ARN

## Monitoring

View logs:
```bash
aws logs tail /ecs/notable-frontend --follow
```

## Cost Estimate (1 task, us-east-1)

- Fargate (0.25 vCPU, 0.5 GB): ~$10/month
- ALB: ~$16/month
- Bedrock Nova Pro: ~$0.0003/query
- Data transfer: Minimal

**Total: ~$26/month + $0.0003 per query**

## Troubleshooting

**Container won't start:**
- Check CloudWatch logs: `/ecs/notable-frontend`
- Verify ECR image exists and task role can pull it

**Backend can't invoke Bedrock:**
- Verify task role has `bedrock:InvokeModel` permission
- Check model ID is correct: `amazon.nova-pro-v1:0`
- Ensure Bedrock is available in your region
- Verify task role ARN is set in task definition

**Health checks failing:**
- Container must respond to `GET /health` within 5 seconds
- Check backend is running: `docker exec -it CONTAINER ps aux`

