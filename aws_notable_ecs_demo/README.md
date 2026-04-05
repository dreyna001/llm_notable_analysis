# Notable Analysis on ECS (Start Here)

This folder deploys the full demo as one ECS container:

`Browser -> ALB -> ECS task (nginx + Flask) -> Amazon Bedrock`

Use this doc first, then run commands from `ECS_DEPLOY.md`.

## What this app does

- Serves the UI from nginx (`index.html`, `main.js`, `styles.css`)
- Sends analysis requests to `POST /api/analyze`
- Calls Bedrock model `amazon.nova-pro-v1:0` from ECS task role
- Exposes `GET /health` for load balancer checks

## Fast path (new reader)

1. Build and push container image to ECR.
2. Create IAM task role with `bedrock:InvokeModel`.
3. Register ECS task definition using that role.
4. Create ECS service + ALB target group (`/health`).
5. Open ALB DNS name and run one test alert.

All copy/paste commands are in `ECS_DEPLOY.md`.

## Required before deploy

- Docker
- AWS CLI authenticated to your target account
- Bedrock model access in your region
- Existing VPC + subnets + security groups + ECS cluster
- ECR repository for this image

## Runtime settings

- **Default model:** `BEDROCK_MODEL_ID=amazon.nova-pro-v1:0`
- **Request timeout:** `GUNICORN_TIMEOUT=300` (set in `supervisord.conf`)
- **Nginx proxy timeout:** `300s` (set in `nginx.conf`)
- **Health endpoint:** `GET /health`

If LLM requests are slow, align ECS/ALB/nginx/gunicorn timeouts.

## Read next

- `ECS_DEPLOY.md` - minimal deployment commands
- `ARCHITECTURE.md` - one-page system flow
- `INFRA_HANDOFF.md` - infra checklist for handoff
- `S3_PIPELINE_DELTA.md` - differences from `s3_notable_pipeline`

