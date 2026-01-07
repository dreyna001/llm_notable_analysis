# Infrastructure Team Handoff

## What You're Getting

A complete ECS-based deployment for the Notable Analysis demo that calls Bedrock directly via IAM roles (no Lambda, no public APIs).

## Directory Structure

```
aws_notable_ecs/
├── index.html                      # Static HTML
├── main.js                         # Client-side JS
├── styles.css                      # GDIT-themed CSS
├── backend.py                      # Flask app (calls Bedrock)
├── ttp_analyzer.py                 # TTP validation logic
├── markdown_generator.py           # Report generation
├── enterprise_attack_v17.1_ids.json # MITRE data
├── backend_requirements.txt        # Python deps
├── Dockerfile                      # Multi-stage build
├── nginx.conf                      # Nginx config
├── supervisord.conf                # Runs nginx + backend
├── ECS_DEPLOY.md                   # ECS deployment guide
├── README.md                       # Overview
├── ARCHITECTURE.md                 # Detailed architecture diagram
└── INFRA_HANDOFF.md                # This file
```

## Deployment Steps (High-Level)

### Phase 1: Build and Push Container (10 minutes)

1. Build Docker image: `docker build -t notable-frontend .`
2. Push to ECR (see `ECS_DEPLOY.md` for commands)

### Phase 2: Create IAM Roles (10 minutes)

**ECS Task Role** (used by backend to call Bedrock):
```json
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
```

### Phase 3: Deploy ECS Service (20 minutes)

1. Create ECS task definition (see `ECS_DEPLOY.md`)
2. Create ECS service in your cluster
3. Attach to ALB (internal or public, your choice)
4. Configure target group with health check: `GET /health`

### Phase 4: Test (5 minutes)

1. Open ALB URL in browser
2. Paste a test alert (e.g., "Suspicious PowerShell execution detected")
3. Click "Analyze Alert"
4. Verify markdown report appears

## Architecture Summary

```
Browser → ALB → ECS (nginx + Flask) → Bedrock
                 └─ Uses task role ──┘
```

- **No Lambda**: All logic runs in ECS container
- **No API Gateway**: Direct Bedrock calls from ECS
- **No API keys**: IAM roles handle all authentication

## Key Configuration Points

### 1. ECS Task Role ARN
File: `task-definition.json` (you'll create this)
```json
"taskRoleArn": "arn:aws:iam::ACCOUNT:role/NotableFrontendTaskRole"
```

### 2. Bedrock Model ID
The backend uses `amazon.nova-pro-v1:0` by default. Can be overridden via environment variable:
```bash
BEDROCK_MODEL_ID=amazon.nova-pro-v1:0
```

### 3. AWS Region
Ensure Bedrock is available in your region. Default is `us-east-1`.

## Security Recommendations

### For Internal Use (Recommended)
- Deploy ALB as `internal` (not `internet-facing`)
- Restrict security groups to corporate VPN CIDR
- Use HTTPS with ACM certificate
- Enable ALB access logs

### For Public Demo (If Required)
- Keep ALB `internet-facing`
- Add AWS WAF with rate limiting
- Consider adding Cognito authentication
- Enable CloudTrail for audit logs

## Resource Requirements

### ECS Task
- CPU: 256 (0.25 vCPU)
- Memory: 512 MB
- Launch type: Fargate
- Desired count: 1 (increase for HA)

### ALB
- Type: Application Load Balancer
- Scheme: Internal or Internet-facing
- Target group: HTTP:80, health check `/health`

## Cost Estimate

### Fixed Monthly (1 ECS task)
- Fargate: ~$10/month
- ALB: ~$16/month
- CloudWatch Logs: ~$1/month
- **Total: ~$27/month**

### Variable (per query)
- Bedrock Nova Pro: ~$0.0003/query

### Example: 200 queries/day
- Fixed: $27/month
- Variable: 6,000 queries × $0.0003 = $1.80/month
- **Total: ~$29/month**

## Monitoring

### CloudWatch Logs
- ECS: `/ecs/notable-frontend`

### Metrics to Watch
- ECS task CPU/memory utilization
- ALB target health
- Bedrock throttling errors
- ECS task count

### Alarms to Create
- ECS task count < 1
- ALB unhealthy target count > 0
- Bedrock throttling errors > 10 in 5 minutes

## Troubleshooting

### "Container health checks failing"
- Verify backend is responding to `GET /health`
- Check CloudWatch logs: `/ecs/notable-frontend`
- Ensure supervisord is running both nginx and backend

### "Bedrock access denied"
- Check ECS task role has `bedrock:InvokeModel` permission
- Verify model ID: `amazon.nova-pro-v1:0`
- Ensure Bedrock is available in your region
- Check task role ARN is correctly set in task definition

### "Analysis requests timing out"
- Check Bedrock API isn't throttling
- Verify ECS task has internet access (NAT gateway if in VPC)
- Increase ALB target group timeout (default 30s, recommend 120s)

## Next Steps After Deployment

1. **Test thoroughly** with various alert types
2. **Set up monitoring** (CloudWatch dashboards, alarms)
3. **Document the ALB URL** for end users
4. **Create runbook** for common issues
5. **Plan for scaling** if usage grows

## Questions?

Contact the development team with:
- ECS cluster name
- ALB DNS name
- Task role ARN
- Any error messages from CloudWatch Logs

## Files to Review

1. **ARCHITECTURE.md** - Detailed architecture diagram and data flow
2. **ECS_DEPLOY.md** - Step-by-step ECS deployment
3. **README.md** - Project overview

All files are self-contained and ready for deployment. No changes to existing `aws_notable_demo/` directory needed.

