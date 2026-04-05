# Architecture (One Page)

## System

```text
Browser
  -> ALB
  -> ECS task (single container)
      - nginx on :80
      - Flask + gunicorn on :8080
  -> Amazon Bedrock (nova-pro)
```

## Request flow

1. User submits alert in UI.
2. Browser sends `POST /api/analyze`.
3. Nginx proxies to Flask backend.
4. Backend calls Bedrock with IAM task role.
5. Backend returns markdown + structured response.
6. UI renders the report.

## Important endpoints

- `GET /health` for target group health checks
- `POST /api/analyze` for analysis requests

## Security model

- No API keys in frontend or container config.
- ECS task role is used for Bedrock auth (`bedrock:InvokeModel`).
- ALB can be internal (recommended for enterprise/private use).

## Timeout model

Long LLM calls require aligned timeouts:

- gunicorn timeout (`GUNICORN_TIMEOUT`, default `300`)
- nginx `proxy_read_timeout` (`300s`)
- ALB idle timeout (set to `>= 300s`)

If these are misaligned, users will see request timeouts even when Bedrock succeeds.
