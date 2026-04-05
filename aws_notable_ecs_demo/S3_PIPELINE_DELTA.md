# ECS vs S3 Pipeline (Quick Delta)

This file explains what exists in `s3_notable_pipeline` but not in this ECS demo.

## Missing safeguards in ECS demo

- Schema validation of model output before processing
- Repair retry when model output is invalid JSON
- Aggressive JSON extraction from mixed text responses
- Full raw-content capture across all fallback paths

## Why this is acceptable here

The ECS demo keeps logic minimal and depends on Bedrock tool-calling for structured output.

## When to add these back

If you see frequent parse errors or malformed responses in production traffic, port these from `s3_notable_pipeline`:

- `validate_response_schema()`
- `REPAIR_PROMPT_TEMPLATE` + retry loop
- `extract_json_object()`
