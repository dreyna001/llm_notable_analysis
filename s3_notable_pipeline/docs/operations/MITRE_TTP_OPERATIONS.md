# MITRE ATT&CK And TTP Operations

This guide helps customers understand and maintain the MITRE ATT&CK TTP ID
validation data used by the AWS Lambda analyzer.

## What This Controls

The analyzer validates generated ATT&CK technique identifiers against a bundled
JSON file shipped inside the Lambda package:

- `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`

Invalid or unsupported technique IDs are filtered out before they appear in
reports. This keeps model output from introducing malformed TTP IDs into
customer-facing artifacts.

There is no runtime `MITRE_IDS_PATH` environment variable on AWS. The validator
loads the bundled file from the deployed container image.

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

1. Update `scripts/extract_ttp_ids.py` to the target MITRE spreadsheet URL.
2. Regenerate `src/s3_notable_pipeline/enterprise_attack_v17.1_ids.json`.
3. Rebuild and push the Lambda container image.
4. Redeploy the stack.
5. Rerun unit tests and representative report checks before promotion.

Do not loosen validation in application code for a single customer. Refresh the
data file through an approved release process instead.

### How should invalid TTP output be handled operationally?

The runtime filters generated TTP IDs against the bundled allowlist. Operators
should review reports where expected mappings are missing. Missing mappings may
indicate:

- the alert lacks enough evidence for a specific technique
- the model produced an unsupported ID
- the bundled MITRE data is stale relative to analyst expectations

CloudWatch logs record counts of valid and invalid TTP IDs during processing.

## Refresh Workflow

From `s3_notable_pipeline`:

```bash
python scripts/extract_ttp_ids.py
python -m pytest tests/test_lambda_handler.py tests/test_markdown_generator.py
```

Then rebuild and publish the Lambda image per `DEPLOYMENT_IMAGE_STEPS.md` and
redeploy the stack.

## Validation And Rollout

1. Confirm the deployed image includes `enterprise_attack_v17.1_ids.json`.
2. Process representative notables with known ATT&CK mappings.
3. Confirm JSON and markdown reports include only valid technique IDs.
4. After an ATT&CK refresh, rerun the pytest slice above and one end-to-end S3
   smoke upload before promotion.

Unit test command:

```bash
python -m pytest tests/test_lambda_handler.py tests/test_markdown_generator.py
```

## Related Docs

- [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md)
- [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- [`../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`](../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md)
- [`../delivery_package/EXECUTIVE_AWS_WORKFLOW.md`](../delivery_package/EXECUTIVE_AWS_WORKFLOW.md)
