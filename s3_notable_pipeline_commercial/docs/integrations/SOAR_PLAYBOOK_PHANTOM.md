# SOAR Playbook (Splunk SOAR / Phantom) - S3 Upload Pattern

Minimal **container-triggered** playbook pattern for feeding the AWS
`s3_notable_pipeline` from Splunk SOAR (Phantom).

**Delivery path:** SOAR uploads one JSON object per notable to the input S3
bucket under `incoming/`. This is **not** the on-prem SFTP file-drop path.

Template script (relative to `s3_notable_pipeline/`):

- [`scripts/soar_playbook/phantom_notable_to_s3.py`](../../scripts/soar_playbook/phantom_notable_to_s3.py)

On-prem equivalents (SFTP delivery to analyzer host):

- Container-triggered: [`../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM.md)
- Notable-index polling: [`../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md)

## When to use this pattern

Use this pattern when:

- SOAR already creates notable containers from Splunk ES
- you want to process the SOAR container plus artifact CEF context directly
- playbook launch on notable container creation/update is reliable in your tenant
- the AWS stack input bucket is reachable from SOAR (directly or through a
  configured AWS S3 app asset)

This repository ships one AWS template (`phantom_notable_to_s3.py`). For
scheduled `index=notable` polling on AWS, adapt the on-prem notable-index
template to S3 upload or extend this playbook.

## Trigger timing

Run this playbook **after the notable exists from the correlation search
pipeline**, not from raw events.

Recommended trigger gates:

- trigger on notable container creation/update in SOAR (`label=notable` in most
  deployments)
- process only notable states you care about (commonly `new` / `open`)
- add dedupe so the same notable is not sent repeatedly (for example by
  `finding_id` plus timestamp window or SOAR custom fields)

The template applies built-in routing gates before upload (see operator constants
below). It does **not** dedupe across repeated playbook runs on the same
container; add that in SOAR if needed.

Unknown (environment-specific, confirm in your SOAR):

- exact field carrying the Splunk ES notable identifier (`source_data_identifier`,
  `event_id`, `finding_id`, `orig_sid`, etc.)
- exact playbook launch event semantics in your Splunk SOAR app/integration
- AWS S3 app action name and parameter keys for `put object`

## Delivery method

Recommended delivery path:

```text
SOAR -> S3 put object -> s3://<INPUT_BUCKET>/incoming/<finding_id>.json
```

- `<INPUT_BUCKET>` is the stack input bucket (`INPUT_BUCKET_NAME` in the
  template).
- `<finding_id>` is sanitized (alphanumeric, `-`, `_`; max 100 chars) and must
  match the JSON `finding_id` field.
- S3 event notifications on the `incoming/` prefix trigger Lambda automatically.

Do **not** use SFTP for AWS intake. SFTP is the on-prem delivery path documented
in the linked on-prem SOAR guides above.

## Operator-tunable constants

Adjust these in
[`phantom_notable_to_s3.py`](../../scripts/soar_playbook/phantom_notable_to_s3.py)
before production use:

| Constant | Default | Purpose |
|----------|---------|---------|
| `AWS_S3_ASSET_NAME` | `aws-s3-placeholder` | SOAR AWS S3 asset |
| `S3_PUT_ACTION` | `put object` | S3 upload action name |
| `INPUT_BUCKET_NAME` | `REPLACE_WITH_INPUT_BUCKET_NAME` | Stack input bucket |
| `INPUT_PREFIX` | `incoming` | S3 key prefix (must match stack trigger) |
| `MAX_SUPPORTING_EVENTS` | `200` | Artifact rows collected via `phantom.collect2` |
| `PROCESS_LABELS` | `notable` | Allowed container labels; empty set allows all |
| `PROCESS_STATUSES` | `new`, `open` | Allowed container statuses; empty set allows all |
| `PROCESS_SEVERITIES` | `medium`, `high`, `critical` | Allowed severities; empty set allows all |

Also validate S3 action parameter keys (`bucket`, `key`, `vault_id`) against
your installed AWS S3 app. Parameter names vary by app version and vendor.

## Finding ID and object key

The template chooses `finding_id` in this order:

1. container `source_data_identifier` (often maps to upstream Splunk notable id)
2. container `id`
3. `"unknown"` fallback

Both JSON `finding_id` and the S3 object key stem are sanitized before upload
as `incoming/<finding_id>.json`.

For `notable_rest` sink mode, the pipeline still writes the markdown report to
the configured output bucket and also derives `finding_id` from the S3 object
key stem for the REST update. Example: `incoming/abc-123.json` ->
`finding_id=abc-123`.

If Splunk writeback is enabled, confirm that object key stem maps to the
intended Splunk `finding_id` or customer-equivalent notable identifier.

## Expected payload shape (template default)

The template is intentionally **format-agnostic**. It does not remap container
fields into a flat Splunk-notable schema. Each uploaded object is
`incoming/<finding_id>.json` with one JSON object like:

```json
{
  "finding_id": "abc-123",
  "ingest_source": "splunk_soar_phantom",
  "captured_at": "2026-03-28T20:16:00Z",
  "notable": {
    "container_id": "42",
    "name": "Suspicious Authentication Pattern",
    "description": "Multiple failed logins followed by success",
    "severity": "high",
    "status": "new",
    "label": "notable",
    "source_data_identifier": "abc-123",
    "create_time": "2026-03-28T20:15:00Z"
  },
  "container": { "...": "full Phantom container dictionary" },
  "supporting_events": [
    {
      "artifact_id": 101,
      "artifact_name": "event",
      "cef": {
        "src": "203.0.113.45",
        "destinationUserName": "DOMAIN\\admin"
      }
    }
  ]
}
```

Notes:

- `supporting_events` is a list of structured artifact records (`artifact_id`,
  `artifact_name`, `cef`), collected from container artifacts.
- `container` preserves the full SOAR container context for audit and analysis.
- One object = one notable container.

Optional payload enhancements (not emitted by the default template):

- add top-level `summary`, `search_name`, `alert_time`, `risk_score`, or
  `threat_category` if you extend `_build_payload`
- add a serialized `raw_event` string if you want an explicit audit blob in
  addition to nested JSON

Lambda accepts arbitrary JSON (or plain text) under `incoming/`. Strongly
preferred correlation fields and size limits are documented in
[`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md).

## Atomic upload consideration

S3 object creation is atomic from Lambda's perspective: the intake trigger
fires on completed `PutObject` calls. Partial local writes in SOAR before upload
do not reach the bucket.

If you add custom staging logic, avoid leaving incomplete objects under
`incoming/` with final `.json` keys.

## Test plan (quick)

1. Deploy the stack and note the input bucket name from stack outputs.
2. Manually run the playbook on one known notable container in a lab SOAR tenant.
3. Confirm routing gates (`label`, `status`, `severity`) behave as expected.
4. Confirm the object appears at
   `s3://<input-bucket>/incoming/<finding_id>.json`.
5. Confirm Lambda invocation in CloudWatch.
6. Confirm output at the configured sink (`s3` or `notable_rest`). In
   `notable_rest`, confirm both the `reports/` object and the Splunk comment
   update.

Manual smoke without SOAR:

```powershell
.\scripts\test-pipeline.ps1
```

See also [`../delivery_package/EXECUTIVE_AWS_WORKFLOW.md`](../delivery_package/EXECUTIVE_AWS_WORKFLOW.md)
for the end-to-end AWS workflow narrative.

## Related docs

- [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) - S3 ingest contract, retention, and validation
- [`../delivery_package/EXECUTIVE_AWS_WORKFLOW.md`](../delivery_package/EXECUTIVE_AWS_WORKFLOW.md) - executive AWS workflow overview
- [`../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM.md) - on-prem container-triggered SFTP pattern
- [`../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../../../llm_notable_analysis_onprem_systemd/docs/integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md) - on-prem notable-index polling pattern
