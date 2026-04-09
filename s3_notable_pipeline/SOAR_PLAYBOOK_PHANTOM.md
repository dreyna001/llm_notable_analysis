# SOAR -> S3 Pattern (Splunk SOAR / Phantom)

Minimal integration pattern for feeding this pipeline from SOAR.

## What to Do

1. Trigger playbook on newly created notables (not raw events).
2. Build one JSON payload per notable.
3. Upload to `s3://<INPUT_BUCKET>/incoming/<finding_id>.json`.
4. Let Lambda process automatically from S3 event notifications.

Template script:

- `soar_playbook/phantom_notable_to_s3.py`

## Minimum Payload

```json
{
  "summary": "Suspicious activity summary",
  "notable_id": "123456",
  "finding_id": "abc-123",
  "search_name": "Detection Name",
  "raw_event": "{\"container\": {...}}"
}
```

Recommended optional fields:

- `event_id`
- `risk_score`
- `threat_category`
- `alert_time`
- `supporting_events` (array)

## Placeholder Values to Replace

In `phantom_notable_to_s3.py`, update:

- `AWS_S3_ASSET_NAME`
- `INPUT_BUCKET_NAME`
- `S3_PUT_ACTION`
- Any app-specific parameter names in `phantom.act(...)`

## Important Mapping Note

For `notable_rest` sink mode, the pipeline still writes the markdown report to the configured output bucket and also derives `finding_id` from the S3 filename stem for the REST update.  
Example: `incoming/abc-123.json` -> `finding_id=abc-123`.

## Quick Validation

1. Run playbook on one known notable.
2. Confirm object appears under `incoming/` in S3.
3. Confirm Lambda invocation in CloudWatch.
4. Confirm output at the configured sink (`s3` or `notable_rest`). In `notable_rest`, confirm both the `reports/` object and the Splunk comment update.
