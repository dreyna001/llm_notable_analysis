# ECS Deploy (Minimal)

This is the shortest path to run this app on ECS Fargate.

## 0) Replace placeholders

Use your own values for:

- `AWS_REGION`
- `AWS_ACCOUNT_ID`
- `ECR_REPO` (example: `notable-frontend`)
- `ECS_CLUSTER`
- `SUBNET_IDS` (comma-separated subnet IDs)
- `SECURITY_GROUP_ID`
- `TARGET_GROUP_ARN`

## 1) Build and push image

```bash
docker build -t notable-frontend .
docker tag notable-frontend:latest AWS_ACCOUNT_ID.dkr.ecr.AWS_REGION.amazonaws.com/ECR_REPO:latest
aws ecr get-login-password --region AWS_REGION | docker login --username AWS --password-stdin AWS_ACCOUNT_ID.dkr.ecr.AWS_REGION.amazonaws.com
docker push AWS_ACCOUNT_ID.dkr.ecr.AWS_REGION.amazonaws.com/ECR_REPO:latest
```

## 2) Create ECS task role

Create role `NotableFrontendTaskRole` with:

- Trust principal: `ecs-tasks.amazonaws.com`
- Permission: `bedrock:InvokeModel`
- Resource: `arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0`

Use IAM console or CLI.

## 3) Register task definition

Save this as `task-definition.json`:

```json
{
  "family": "notable-frontend",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::AWS_ACCOUNT_ID:role/NotableFrontendTaskRole",
  "containerDefinitions": [
    {
      "name": "notable-frontend",
      "image": "AWS_ACCOUNT_ID.dkr.ecr.AWS_REGION.amazonaws.com/ECR_REPO:latest",
      "portMappings": [
        {
          "containerPort": 80,
          "protocol": "tcp"
        }
      ],
      "essential": true,
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/notable-frontend",
          "awslogs-region": "AWS_REGION",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Register it:

```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

## 4) Create ECS service

```bash
aws ecs create-service \
  --cluster ECS_CLUSTER \
  --service-name notable-frontend \
  --task-definition notable-frontend \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[SUBNET_IDS],securityGroups=[SECURITY_GROUP_ID],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=TARGET_GROUP_ARN,containerName=notable-frontend,containerPort=80"
```

## 5) Configure ALB

- Forward listener traffic to `TARGET_GROUP_ARN`
- Target group health check path: `/health`
- ALB idle timeout: set to at least `300s` for long LLM calls

## 6) Verify

- Open ALB DNS name in browser
- Submit test alert
- Confirm report output appears

Logs:

```bash
aws logs tail /ecs/notable-frontend --follow
```

## Common failures

- `AccessDeniedException`: task role missing `bedrock:InvokeModel`
- Unhealthy target: container not serving `GET /health`
- Timeouts: ALB idle timeout lower than nginx/gunicorn timeout
