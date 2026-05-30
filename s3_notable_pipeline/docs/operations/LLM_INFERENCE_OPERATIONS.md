# AWS LLM Inference Operations

## What This Controls

The AWS pipeline uses Amazon Bedrock for notable analysis. Optional parity
features can add retrieval and additional model calls, so Lambda resources must
be sized with the active capability profile in mind.

## Recommended Starting Posture

- Keep the default Bedrock model id supplied by the deployment templates unless
  the customer approves a model change.
- Use the default Lambda settings for `core`.
- Start heavier profiles at `LambdaTimeoutSeconds=900` and
  `LambdaMemorySize=1024`, then tune from CloudWatch evidence.

## Config Quick Reference

| Area | Parameter / env |
|------|------------------|
| Bedrock model | `BEDROCK_MODEL_ID` |
| Capability bundle | `CapabilityProfiles` / `CAPABILITY_PROFILES` |
| Timeout | `LambdaTimeoutSeconds` |
| Memory | `LambdaMemorySize` |
| Ephemeral storage | `LambdaEphemeralStorageMb` |

## Validation And Rollout

1. Run unit tests before deployment.
2. Deploy to a non-production AWS account.
3. Upload one representative notable and confirm markdown/JSON outputs.
4. Review Lambda duration, memory, timeout, and Bedrock error metrics.
5. Increase resources only when measured behavior requires it.

## Known Limits

Local tests mock Bedrock and validate orchestration. They do not validate
account quotas, model access, cross-region behavior, IAM conditions, or Bedrock
Knowledge Base quality.
