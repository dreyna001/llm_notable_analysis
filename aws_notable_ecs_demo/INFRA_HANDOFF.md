# Infrastructure Handoff (Checklist)

Use this when handing deployment to an infra team.

## Inputs infra team must provide

- AWS account and region
- ECS cluster
- VPC/subnets/security groups
- ALB + target group
- ECR repository

## Deployment checklist

1. Build and push image from this folder to ECR.
2. Create IAM role `NotableFrontendTaskRole` with `bedrock:InvokeModel`.
3. Register ECS task definition using:
   - image from ECR
   - `taskRoleArn` for Bedrock
   - health check `GET /health`
4. Create ECS service (Fargate) attached to ALB target group.
5. Set ALB idle timeout to `>= 300s`.
6. Validate UI by running one analysis end-to-end.

For exact commands, use `ECS_DEPLOY.md`.

## Minimum IAM permissions

- ECS task execution role: pull ECR image + write CloudWatch logs
- ECS task role: `bedrock:InvokeModel` on `amazon.nova-pro-v1:0`

## Handoff outputs to capture

- ALB DNS name
- ECS service name
- ECS task definition revision
- Task role ARN
- CloudWatch log group (`/ecs/notable-frontend`)

## Smoke test

1. Open ALB URL.
2. Submit test alert text.
3. Confirm report renders and no 5xx errors in logs.

## First troubleshooting checks

- Unhealthy target: verify container serves `GET /health`
- Bedrock access denied: verify task role policy and `taskRoleArn`
- Timeouts: verify ALB/nginx/gunicorn timeout alignment
