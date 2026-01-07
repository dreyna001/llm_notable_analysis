# Notable Analysis - ECS Deployment

ECS-based deployment where all analysis logic runs in a single container.

## Architecture

```
Browser → ALB → ECS Container (nginx + Flask + Bedrock) → Bedrock Nova Pro
```

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

