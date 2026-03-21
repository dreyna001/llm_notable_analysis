# Architecture Overview

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Browser                            │
│  (Opens ECS ALB URL, submits alert via HTML form)               │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Application Load Balancer                    │
│              (Public or Internal, HTTPS optional)               │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        ECS Fargate Task                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Docker Container                      │   │
│  │  ┌────────────────┐          ┌────────────────────────┐  │   │
│  │  │  nginx:80      │          │  Flask Backend:8080    │  │   │
│  │  │                │          │                        │  │   │
│  │  │  Serves:       │  Proxy   │  - Receives POST       │  │   │
│  │  │  - index.html  │  /api/*  │    /api/analyze        │  │   │
│  │  │  - main.js     │  ──────> │  - Uses boto3 +        │  │   │
│  │  │  - styles.css  │          │    ECS Task Role       │  │   │
│  │  │                │          │  - Calls Bedrock       │  │   │
│  │  │                │          │  - ttp_analyzer.py     │  │   │
│  │  │                │          │  - markdown_generator  │  │   │
│  │  └────────────────┘          └────────┬───────────────┘  │   │
│  │                                       │                  │   │
│  │                                       │ AWS SDK          │   │
│  └───────────────────────────────────────┼──────────────────┘   │
│                                          │                      │
│  Task Role: bedrock:InvokeModel          │                      │
└──────────────────────────────────────────┼──────────────────────┘
                                           │
                                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Amazon Bedrock                             │
│                   Model: amazon.nova-pro-v1:0                   │
│                                                                 │
│  - Analyzes security alerts                                     │
│  - Identifies MITRE ATT&CK TTPs                                 │
│  - Generates structured JSON response                           │
└─────────────────────────────────────────────────────────────────┘
```

## Request Flow

### 1. User Interaction
```
User fills form → Clicks "Analyze" → main.js sends POST /api/analyze
```

### 2. Frontend Processing
```
nginx receives request → Proxies to Flask backend (127.0.0.1:8080)
```

### 3. Backend Processing
```python
Flask backend:
  1. Validates request JSON
  2. Normalizes alert data
  3. Calls BedrockAnalyzer with prompt
  4. Validates TTPs against MITRE data
  5. Generates markdown report
  6. Returns JSON with markdown + structured data
```

### 4. Response Display
```javascript
main.js:
  1. Receives JSON response
  2. Renders markdown in result pane
  3. Displays TTP cards with scores
```

## Data Flow

```
Alert Text/JSON
    ↓
[Browser Form]
    ↓ (POST /api/analyze)
{
  "payload": "...",
  "payload_type": "raw_text"
}
    ↓
[ECS Backend]
    ↓ (Bedrock API)
{
  "modelId": "amazon.nova-pro-v1:0",
  "messages": [
    {
      "role": "user",
      "content": [{"text": "Analyze this alert..."}]
    }
  ],
  "inferenceConfig": {...}
}
    ↓
[Bedrock Nova Pro]
    ↓ (Structured JSON)
{
  "ttp_analysis": [...],
  "attack_chain": {...},
  "ioc_extraction": {...}
}
    ↓
[ECS Backend Response]
    ↓ (HTTP 200)
{
  "markdown": "# Alert Analysis...",
  "llm_response": {...},
  "scored_ttps": [...]
}
    ↓
[Browser Display]
```

## Security Model

### Authentication & Authorization

1. **Browser → ALB**: 
   - Can be public or internal
   - Optional: Add Cognito, WAF, IP allowlist

2. **ALB → ECS**:
   - Private communication within VPC
   - Security group controls access

3. **ECS → Bedrock**:
   - **No API keys or tokens needed**
   - ECS task role provides IAM credentials
   - Task role grants `bedrock:InvokeModel`

### IAM Roles

```
ECS Task Execution Role (pulls image, writes logs):
  - ecr:GetAuthorizationToken
  - ecr:BatchCheckLayerAvailability
  - ecr:GetDownloadUrlForLayer
  - ecr:BatchGetImage
  - logs:CreateLogStream
  - logs:PutLogEvents

ECS Task Role (calls Bedrock):
  - bedrock:InvokeModel on arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0
```

## Deployment Sequence

1. **Build Container**
   - Docker build
   - Push to ECR

2. **Create ECS Resources**
   - Task definition (references ECR image)
   - Task role (with Bedrock invoke permission)
   - Service (runs task)
   - ALB + target group

3. **Test**
   - Open ALB URL
   - Submit test alert
   - Verify analysis appears

## Cost Breakdown

### Per-Query Costs
- Bedrock Nova Pro tokens: ~$0.0003
- **Total per query: ~$0.0003**

### Fixed Monthly Costs (1 task)
- Fargate (0.25 vCPU, 0.5GB): ~$10
- ALB: ~$16
- CloudWatch Logs: ~$1
- **Total fixed: ~$27/month**

### Scaling
- 200 queries/day = 6,000/month = $1.80 in query costs
- **Total for 200 queries/day: ~$29/month**

## Why This Architecture?

1. **Single container**: All logic (frontend + backend + analysis) in one place
2. **VPC control**: ALB can be internal, restricting access to VPN/corporate network
3. **No Lambda overhead**: Direct Bedrock calls from ECS
4. **Standard patterns**: ECS + ALB is a common enterprise pattern
5. **IAM-based security**: No API keys to manage, rotate, or leak

