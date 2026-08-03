# MITRE ATT&CK And TTP Operations

This guide helps customers understand and maintain the MITRE ATT&CK TTP ID
validation data used by the AWS Lambda analyzer.

## What This Controls

The analyzer validates generated ATT&CK technique identifiers against a bundled
JSON allowlist. Invalid IDs are removed from `ttp_analysis` before reports are
written; the service does not rewrite or substitute IDs.

Implementation: `src/s3_notable_pipeline/ttp_analyzer.py` (`TTPValidator`,
applied in `BedrockAnalyzer.analyze_ttp()` after LLM output is parsed, schema-
validated, and content-policy checked).

Bundled file (shipped in the Lambda package via `pyproject.toml` package data):

- Source tree: `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`
- Runtime resolution: `Path(__file__).parent / "enterprise_attack_v17.1_ids.json"`
  next to `ttp_analyzer.py` in the deployed image

There is no runtime `MITRE_IDS_PATH` environment variable on AWS. Refresh ATT&CK
data by rebuilding and redeploying the Lambda container image.

## Bundled Data

| Item | Value |
|------|-------|
| ATT&CK release | Enterprise v17.1 |
| Technique IDs | 679 total (211 parent, 468 sub-technique) |
| ID format | `T####` or `T####.###` |
| JSON shape | Flat array of strings, e.g. `["T1001", "T1003.001", ...]` |

The validator splits IDs on `.` to track parent techniques and sub-techniques
separately; only exact matches pass.

## Recommended Starting Posture

- Use the bundled ATT&CK v17.1 ID file from the deployed Lambda image.
- Treat ATT&CK data updates as a release event: regenerate the JSON, rebuild the
  Lambda image, redeploy, and rerun representative report checks.
- Keep the selected ATT&CK version documented for analyst review and repeatability.

## Customer Decisions

### Which ATT&CK version should be used?

The default bundled file targets MITRE ATT&CK Enterprise v17.1. Prompts and
validation logic assume v17-style technique IDs (`T####` or `T####.###`).

If the customer requires a newer ATT&CK release:

1. Update the MITRE spreadsheet URL in `scripts/extract_ttp_ids.py`.
2. Regenerate `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`.
3. Rebuild and push the Lambda container image.
4. Redeploy the stack.
5. Rerun tests and representative report checks before promotion.

Do not loosen validation in application code for a single customer. Refresh the
data file through an approved release process instead.

### How should invalid TTP output be handled operationally?

After LLM parsing, `filter_valid_ttps()` keeps only entries whose `ttp_id` is
in the allowlist. Filtered IDs are logged at WARNING; each analysis logs the
loaded allowlist size and final valid TTP count at INFO.

Operators should review reports where expected mappings are missing. Missing
mappings may indicate:

- the alert lacks enough evidence for a specific technique
- the model produced an unsupported ID
- the bundled MITRE data is stale relative to analyst expectations

**Invocation behavior:** if the IDs file is missing, unreadable, empty, or invalid
JSON, `BedrockAnalyzer` initialization fails and the Lambda invocation errors
before analysis completes.

## Refresh Workflow

From `s3_notable_pipeline`:

```bash
python scripts/extract_ttp_ids.py
python -m pytest tests/test_ttp_analyzer_prompts.py tests/test_lambda_handler.py tests/test_markdown_generator.py
```

Then rebuild and publish the Lambda image per
[`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md)
and redeploy the stack.

## Validation And Rollout

1. Confirm the deployed image includes `enterprise_attack_v17.1_ids.json` beside
   `ttp_analyzer.py`.
2. Process representative notables with known ATT&CK mappings.
3. Confirm JSON and markdown reports include only valid technique IDs.
4. After an ATT&CK refresh, rerun the pytest slice above and one end-to-end S3
   smoke upload before promotion.

## Related Docs

- [`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md)
- [`../deployment/DEPLOYMENT_IMAGE_STEPS.md`](../deployment/DEPLOYMENT_IMAGE_STEPS.md)
- [`../../security/ATTACK_LLM_ANALYSIS.md`](../../security/ATTACK_LLM_ANALYSIS.md)
- [`../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)
- [`../../delivery_package/EXECUTIVE_AWS_WORKFLOW.md`](../../delivery_package/EXECUTIVE_AWS_WORKFLOW.md)
