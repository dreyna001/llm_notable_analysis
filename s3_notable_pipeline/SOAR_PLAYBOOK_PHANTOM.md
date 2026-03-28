# SOAR Playbook (Splunk SOAR / Phantom) - S3 Pipeline

This guide provides a minimal playbook pattern for environments where:

- SOAR orchestrates notable handling.
- `s3_notable_pipeline` is triggered by S3 object uploads.
- One notable (plus supporting context) is written as one `*.json` object to `incoming/`.

Template code in this repo:

- `s3_notable_pipeline/soar_playbook/phantom_notable_to_s3.py`

## 1) Trigger timing (when to run)

Run the SOAR playbook **after correlation searches create the notable**, not on raw events.

Recommended trigger gates:

- Process notable containers/events only (commonly `label=notable`).
- Gate by status (for example `new` / `open`).
- Optionally gate by severity (for example `medium+`).
- Dedupe by notable correlation identifier so you avoid re-uploading the same notable repeatedly.

Unknown (environment-specific, verify in your SOAR and Splunk ES):

- Exact field name that carries the notable correlation ID (`event_id`, `finding_id`, `orig_sid`, etc.).
- Exact launch semantics from your SOAR notable integration app.

## 2) Notable quality checklist before writing to S3

Before uploading to S3, ensure the payload contains at least:

- `summary` (required by your intended contract)
- stable identifier (`notable_id`, plus `event_id` / `finding_id`)
- `search_name`
- useful top-level context fields (`user`, `src_ip`, `dest_host`, etc.)

Recommended:

- Include full source context as a serialized `raw_event` string.
- Include `supporting_events` as a top-level list of strings.

## 3) Expected object location

Upload each notable to:

- `s3://<INPUT_BUCKET>/incoming/<finding_id>.json`

`s3_notable_pipeline/lambda_handler.py` expects:

- S3 event-driven `ObjectCreated` for the input bucket
- keys under the `incoming/` prefix

## 4) Example payload

```json
{
  "summary": "Multiple failed logins followed by success for DOMAIN\\admin from 203.0.113.45",
  "notable_id": "123456",
  "event_id": "abc-123",
  "finding_id": "abc-123",
  "search_name": "Suspicious Authentication Pattern",
  "risk_score": 80,
  "threat_category": "Credential Access",
  "alert_time": "2026-03-28T20:16:00Z",
  "supporting_events": [
    "{\"src_ip\":\"203.0.113.45\",\"user\":\"DOMAIN\\\\admin\",\"action\":\"failure\"}",
    "{\"src_ip\":\"203.0.113.45\",\"user\":\"DOMAIN\\\\admin\",\"action\":\"success\"}"
  ],
  "raw_event": "{\"container\": {...}, \"supporting_events\": [...]}"
}
```

## 5) Placeholder values you must replace

In `phantom_notable_to_s3.py`, replace:

- `AWS_S3_ASSET_NAME`
- `INPUT_BUCKET_NAME`
- `S3_PUT_ACTION` (if your installed app uses a different action name)
- action parameter keys in the `phantom.act(...)` params block (varies by SOAR app)

## 6) Quick test plan

1. Run playbook on one known notable.
2. Verify `incoming/<finding_id>.json` object appears in S3 input bucket.
3. Verify Lambda invocation occurs for that object.
4. Verify sink output (S3 report, Splunk HEC, or Splunk REST per configured mode).
5. Verify correlation identifier mapping still works for REST mode (`finding_id` derived from key stem).
