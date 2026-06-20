# AWS LLM Inference Operations

This guide helps operators tune the Amazon Bedrock call path without changing
code. Settings come from SAM/CloudFormation parameters in
[`deploy/aws/template-sam.yaml`](../../../deploy/aws/template-sam.yaml) and the
Lambda environment variables they populate. This doc covers Bedrock model routing,
inference profile ARNs, Lambda timeout and memory sizing, structured output
behavior, and optional runtime overrides.

## What This Controls

The AWS pipeline calls Amazon Bedrock through the Bedrock Runtime **Converse**
API (`BedrockAnalyzer` in `ttp_analyzer.py`). The S3-triggered
`notable-analyzer-s3` Lambda reads `BEDROCK_MODEL_ID`, invokes Bedrock for main
notable analysis, and optionally makes additional bounded Bedrock calls when
investigation profiles are enabled.

Optional parity features (RAG retrieval, SPL or Elastic query generation,
query-result interpretation, analyst portal chat) add Bedrock or retrieve
traffic. Size Lambda timeout, memory, and concurrency with the active
[`CapabilityProfiles`](../platform/CAPABILITY_PROFILES.md) in mind.

## Recommended Starting Posture

Use template defaults unless CloudWatch evidence shows a need to change them.

| Setting | `core` default | Heavier profiles starting point |
|---------|----------------|----------------------------------|
| `LambdaTimeoutSeconds` | `360` | `900` |
| `LambdaMemorySize` | `512` | `1024` |
| `LambdaEphemeralStorageMb` | `512` | `512` (raise only when measured I/O requires it) |
| `LambdaReservedConcurrentExecutions` | `5` | tune from downstream Bedrock and SIEM limits |

Additional posture:

- Keep the default Bedrock inference profile supplied by the SAM template unless
  the customer approves a model change and updates both `BEDROCK_MODEL_ID` and
  matching IAM in the template.
- Start with `CapabilityProfiles=core` and `SplunkSinkMode=s3` before enabling
  profiles that add extra Bedrock calls.
- Increase Lambda timeout only after measuring end-to-end duration in
  CloudWatch; a single notable can invoke Bedrock more than once when
  `spl_readonly`, `elastic_readonly`, or `QUERY_RESULT_INTERPRETATION_ENABLED`
  are active.

## Customer Decisions

### Which Bedrock model or inference profile should Lambda call?

**SAM parameters:** `AwsAccountId` (required at deploy)

**Lambda env:** `BEDROCK_MODEL_ID`

The SAM template sets `BEDROCK_MODEL_ID` to a **Claude Sonnet 4.6 inference
profile ARN** in `us-east-1`:

```text
arn:aws:bedrock:us-east-1:<AwsAccountId>:inference-profile/us.anthropic.claude-sonnet-4-6
```

- `<AwsAccountId>` is the deploying account's 12-digit ID. There is no template
  default; pass it at deploy time, for example
  `sam deploy --parameter-overrides AwsAccountId=123456789012 ...`.
- The inference profile slug is `us.anthropic.claude-sonnet-4-6`.
- IAM on `notable-analyzer-s3` grants `bedrock:InvokeModel` on the same
  inference profile ARN. Changing the model requires updating both the env var
  and the IAM resource in `template-sam.yaml`.
- The profile ARN region is **hardcoded to `us-east-1`** in the template even
  when the stack deploys elsewhere. Confirm the account has access to this
  inference profile in `us-east-1` before rollout.

`lambda_handler.py` passes `config.BEDROCK_MODEL_ID` into `BedrockAnalyzer`;
startup fails when it is empty.

**Analyst portal chat (separate function):** `PortalApiFunction` receives the
same default `BEDROCK_MODEL_ID`. Optional override:
`PortalChatBedrockModelId` / `PORTAL_CHAT_BEDROCK_MODEL_ID`. When blank, portal
chat falls back to `BEDROCK_MODEL_ID`.

### How should Lambda timeout and memory be sized?

**SAM parameters:** `LambdaTimeoutSeconds`, `LambdaMemorySize`,
`LambdaEphemeralStorageMb`, `LambdaReservedConcurrentExecutions`

| Parameter | Default | Allowed range |
|-----------|---------|---------------|
| `LambdaTimeoutSeconds` | `360` | `1`–`900` |
| `LambdaMemorySize` | `512` | `128`–`10240` |
| `LambdaEphemeralStorageMb` | `512` | `512`–`10240` |
| `LambdaReservedConcurrentExecutions` | `5` | `1`–`100` |

`NotableAnalyzerFunction` uses these values directly. Budget for:

- Main analysis: up to three Converse retries in tool mode, up to three in raw
  JSON fallback mode, plus one schema repair call on parse/validation failure.
- `spl_readonly` / `elastic_readonly`: one additional Bedrock call for query
  generation per notable when enabled.
- Optional `QUERY_RESULT_INTERPRETATION_ENABLED=true`: one additional Bedrock
  call (plus one repair attempt on validation failure) after read-only queries
  run.
- Bedrock client read timeout defaults to `300` seconds (see runtime overrides
  below); Lambda timeout must exceed expected Bedrock plus non-LLM work.

**Other Lambda functions in the same template:**

| Function | Timeout source | Default |
|----------|----------------|---------|
| `notable-analyzer-s3` | `LambdaTimeoutSeconds` | `360` |
| `notable-case-embed` (when CaseIndex enabled) | hardcoded | `900` |
| `notable-portal-api` (when portal enabled) | `PortalChatTimeoutSec` | `300` |

Portal HTTP API integration timeout is `30000` ms; long chat uses the optional
Function URL path when `PortalChatFunctionUrlEnabled=true`.

### How is structured output enforced?

Main notable analysis uses Bedrock Converse with a forced tool call:

1. **Primary path:** `toolConfig` with tool `analyze_notable` and
   `toolChoice` forcing that tool. The tool input schema defines the structured
   analysis contract (TTP analysis, IOC extraction, verdict, competing
   hypotheses, and related fields).
2. **Transport fallback:** On `ModelErrorException` with a tool-use invalid
   sequence, the handler switches to **raw JSON mode** (`use_tool=False`, no
   `toolConfig`) and retries (up to three attempts with exponential backoff).
3. **Parse and validate:** Response is parsed from the `toolUse` block when
   tool mode succeeded, or from assistant text in raw JSON mode. Deterministic
   schema, content-policy, and MITRE ATT&CK allowlist validation run next.
4. **Repair:** One additional Converse call with a repair prompt when initial
   parse/validation fails. Metadata records `repair_attempted`.
5. **PoC fallback:** If validation still fails, the workflow stores raw model
   text with `poc_unstructured_output: true` for human review instead of
   treating the output as validated analysis.

Secondary Bedrock calls (SPL generation, Elastic query generation, query-result
interpretation) use raw JSON mode (`use_tool=False`) with text extraction,
contract validation, and profile-specific repair where implemented. They do not
use the `analyze_notable` tool schema.

Generation settings in code (no SAM parameters today):

| Setting | Source | Default |
|---------|--------|---------|
| `maxTokens` | `MAX_OUTPUT_TOKENS` env | `8192` (clamped `256`–`8192`) |
| `temperature` | fixed in code | `0.1` for analysis calls |
| Bedrock read timeout | `BEDROCK_READ_TIMEOUT_SECONDS` env | `300` (clamped `30`–`900`) |
| Bedrock connect timeout | `BEDROCK_CONNECT_TIMEOUT_SECONDS` env | `10` (clamped `1`–`60`) |
| Converse retries | fixed in code | up to `3` per mode with backoff |

Portal chat synthesis uses plain Converse text output (no tool schema),
`CASE_QA_MAX_ANSWER_TOKENS` (SAM default `800`), and `temperature: 0.0`.

## Config Quick Reference

### SAM parameters (notable analyzer)

| Parameter | Lambda env | Default | Purpose |
|-----------|------------|---------|---------|
| `AwsAccountId` | _(ARN construction)_ | required | Account ID in inference profile ARN |
| `CapabilityProfiles` | `CAPABILITY_PROFILES` | `core` | Feature bundles affecting call count |
| `LambdaTimeoutSeconds` | _(function Timeout)_ | `360` | `notable-analyzer-s3` max duration |
| `LambdaMemorySize` | _(function MemorySize)_ | `512` | Analyzer memory |
| `LambdaEphemeralStorageMb` | _(EphemeralStorage)_ | `512` | `/tmp` size |
| `LambdaReservedConcurrentExecutions` | _(reserved concurrency)_ | `5` | Cap parallel invocations |

`BEDROCK_MODEL_ID` is not a deploy-time parameter; the template sets it from
`AwsAccountId` as shown above.

### Runtime-only env overrides (no SAM parameter)

Set these on the Lambda function only when measured behavior requires it:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MAX_OUTPUT_TOKENS` | `8192` | Converse `maxTokens` for analyzer Bedrock calls |
| `BEDROCK_READ_TIMEOUT_SECONDS` | `300` | Bedrock Runtime client read timeout |
| `BEDROCK_CONNECT_TIMEOUT_SECONDS` | `10` | Bedrock Runtime client connect timeout |
| `QUERY_RESULT_INTERPRETATION_ENABLED` | `false` | Optional third analysis call after queries |
| `PORTAL_CHAT_BEDROCK_MODEL_ID` | empty | Portal chat model override |

See [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
for profile-driven Bedrock call counts and
[`config.env.example`](../../../config.env.example) for local/lab env names.

## Validation And Rollout

1. Run unit tests from `s3_notable_pipeline/`:
   `python -m pytest tests -q`.
2. Deploy to a non-production account with
   `CapabilityProfiles=core` and confirm `AwsAccountId` matches the target
   account.
3. Verify Bedrock access: account enabled for Claude Sonnet 4.6 inference
   profile `us.anthropic.claude-sonnet-4-6` in `us-east-1`, and IAM allows
   `bedrock:InvokeModel` on the deployed ARN.
4. Upload one representative notable and confirm markdown and JSON under
   `reports/`. Check JSON metadata for `model`, `repair_attempted`, and
   absence of `poc_unstructured_output` on the happy path.
5. Review CloudWatch for Lambda duration, memory use, timeout counts, and
   Bedrock `ModelErrorException` or throttling.
6. Add one capability profile at a time; re-measure duration before raising
   `LambdaTimeoutSeconds` or `LambdaMemorySize`.
7. Change one inference setting at a time between validation runs.

## Known Limits

Local tests mock Bedrock and validate orchestration. They do not validate
account quotas, model access, cross-region inference profile routing, IAM
conditions, or Bedrock Knowledge Base quality.

## Related Docs

- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) —
  profiles that add Bedrock calls
- [`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md) —
  build and SAM deploy
- [`../../../deploy/aws/template-sam.yaml`](../../../deploy/aws/template-sam.yaml) —
  authoritative parameter defaults
- [`../../../README.md`](../../../README.md) — fast-path deploy scripts
- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md) — Bedrock KB retrieval
  (advisory context, not observed evidence)
- [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) —
  portal chat timeout and Function URL
- [`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md) —
  LLM boundary and validation posture
- [`../../testing/TESTING.md`](../../testing/TESTING.md) — unit and integration
  test matrix
