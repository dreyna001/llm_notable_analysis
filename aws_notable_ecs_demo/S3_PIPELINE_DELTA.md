# ECS vs S3 Pipeline - Feature Delta

Features implemented in `s3_notable_pipeline/` but **not** in `aws_notable_ecs_demo/`:

| Feature | S3 Pipeline | ECS | Notes |
|---------|-------------|-----|-------|
| Schema validation | `validate_response_schema()` | No | Validates required keys + types before proceeding |
| Repair retry | `REPAIR_PROMPT_TEMPLATE` + retry loop | No | One retry with error context if parse/validation fails |
| JSON extraction | `extract_json_object()` | No | Strips markdown fences, preamble from raw text fallback |
| `last_raw_content` storage | On text fallback + repair | Partial | ECS stores on fallback only |

## Why excluded

Per design decision: ECS uses **tool-calling only** for output enforcement. Schema validation and repair retry add complexity mainly useful for edge-case recovery—tool calling should handle the common path.

If ECS encounters repeated failures, consider porting `validate_response_schema` and `REPAIR_PROMPT_TEMPLATE` from the S3 pipeline.
