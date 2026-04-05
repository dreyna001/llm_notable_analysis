## ATT&CK Grounding in `s3_notable_pipeline`

This note explains how the pipeline keeps LLM analysis constrained and defensible.

## Goal

Turn a notable into ATT&CK-oriented output without allowing free-form or unsupported technique IDs.

## Guardrails

- Load allowed ATT&CK IDs from `enterprise_attack_v17.1_ids.json`.
- Include the allowed ID set in the LLM prompt.
- Parse and normalize model output into a known schema.
- Drop any `ttp_id` that is not in the allowed ATT&CK set.
- Keep `last_llm_response` for reporting/debugging, while only scoring validated TTPs.

## Evidence Discipline

- Prompts require evidence-vs-inference separation.
- Unknown/missing context should remain `unknown` instead of being fabricated.
- Confidence is represented numerically and adjusted by evidence quality.

## Runtime Flow

1. `lambda_handler.py` reads S3 object content.
2. `ttp_analyzer.py` normalizes input and builds the constrained prompt.
3. Bedrock is called with retries/backoff.
4. Response is parsed and repaired if needed.
5. TTP IDs are validated against the local ATT&CK dataset.
6. `markdown_generator.py` renders the final report.

## Updating ATT&CK IDs

When moving to a newer ATT&CK release:

1. Regenerate `enterprise_attack_v17.1_ids.json` from official ATT&CK data.
2. Keep validator/prompt logic unchanged unless schema requirements changed.
3. Re-run pipeline tests with known alerts and compare outputs.
