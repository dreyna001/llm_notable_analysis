# Notable Analysis - ECS Deployment

ECS-based deployment where all analysis logic runs in a single container.

## Architecture

```
Browser → ALB → ECS Container (nginx + Flask + Bedrock) → Bedrock Nova Pro
```

## Timeouts (LLM calls can exceed 30s)

If you see `WORKER TIMEOUT` in logs with a traceback starting at `gunicorn/workers/sync.py`, that's gunicorn's **default 30 second timeout** killing the request while the LLM call is still running.

This container uses **nginx → gunicorn (Flask)**. You need to align timeouts across:

- **gunicorn**: request execution timeout (default 30s)
- **nginx**: `proxy_read_timeout` / `proxy_send_timeout`
- **ALB** (if used): **idle timeout** (AWS default is often 60s)

### Gunicorn knobs (set via env vars)

`supervisord.conf` supports these environment variables:

- **`GUNICORN_TIMEOUT`**: seconds before gunicorn kills a worker handling a request (default: `300`)
- **`GUNICORN_GRACEFUL_TIMEOUT`**: graceful shutdown window (default: `30`)
- **`GUNICORN_WORKERS`**: number of workers (default: `2`)
- **`GUNICORN_KEEPALIVE`**: keep-alive seconds (default: `2`)

Example (local docker):

```bash
docker run --rm -p 8081:80 ^
  -e GUNICORN_TIMEOUT=300 ^
  -e GUNICORN_WORKERS=2 ^
  notable-frontend
```

### Preferred production approach (beyond “just increase timeout”)

Increasing the timeout is fine for a demo, but a long LLM call keeps a web worker busy. For higher reliability/scale, prefer:

- **Async job**: enqueue analysis (SQS/Celery/Step Functions), return a `job_id`, poll `/api/status/<job_id>` or push via SSE/WebSocket
- **Streaming**: stream partial output (SSE/chunked), paired with nginx buffering off and appropriate proxy timeouts

## Files

- `index.html`, `styles.css`, `main.js` - Frontend UI
- `backend.py` - Flask API that calls Bedrock
- `ttp_analyzer.py` - TTP analysis logic
- `markdown_generator.py` - Report generation
- `Dockerfile` - Container build
- `nginx.conf`, `supervisord.conf` - Container runtime

## Quick Deploy

See `ECS_DEPLOY.md` for full deployment instructions.

### 1. Build Container

```bash
docker build -t notable-frontend .
docker tag notable-frontend:latest YOUR_ECR_REPO/notable-frontend:latest
docker push YOUR_ECR_REPO/notable-frontend:latest
```

### 2. Deploy to ECS

Create ECS task definition, service, and ALB (see `ECS_DEPLOY.md`).

### 4. Upload Static Files to S3

```bash
aws s3 cp index.html s3://YOUR-BUCKET-NAME/
aws s3 cp styles.css s3://YOUR-BUCKET-NAME/
aws s3 cp main.js s3://YOUR-BUCKET-NAME/
```

Replace `YOUR-BUCKET-NAME` with the `BucketName` from outputs.

### 5. Open the Website

Navigate to the `WebsiteURL` from outputs in your browser.

Example: `http://notable-demo-ui-123456789012.s3-website-us-east-1.amazonaws.com`

## Pros vs Lambda UI

- Separate concerns (static assets vs API)
- Standard web hosting pattern
- Can use CDN (CloudFront) easily

## Cons vs Lambda UI

- More deployment steps (deploy + upload)
- Public S3 bucket (website mode requires public access)
- Need to update `main.js` manually with API URL
- Two resources to manage (bucket + API)

## Cleanup

```bash
# Delete stack
sam delete --stack-name notable-demo-s3

# Manually empty and delete bucket if needed
aws s3 rm s3://YOUR-BUCKET-NAME --recursive
aws s3 rb s3://YOUR-BUCKET-NAME
```

## When to Use This

Use S3 static hosting if:
- You want standard web hosting architecture
- You plan to add CloudFront CDN
- You prefer separate HTML/CSS/JS files

Use Lambda UI (main deployment) if:
- You want simplest deployment (1 step)
- You want everything in one template
- You don't need public S3 bucket

