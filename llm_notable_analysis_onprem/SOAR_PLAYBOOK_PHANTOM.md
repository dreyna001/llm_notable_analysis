# SOAR Playbook (Splunk SOAR / Phantom)

This guide provides a minimal playbook pattern for environments where:

- SOAR orchestrates notable handling.
- `llm_notable_analysis_onprem` consumes dropped `*.json` / `*.txt` files.
- The file should contain one notable plus supporting event context.

The accompanying template code is in:

- `llm_notable_analysis_onprem/soar_playbook/phantom_notable_to_analyzer.py`

## 1) Trigger Timing (when to run playbook)

Your requirement is correct: run this playbook **after the notable exists from the correlation search pipeline**, not from raw events.

Recommended trigger gates:

- Trigger on notable container creation/update in SOAR (`label=notable` in most deployments).
- Process only notable states you care about (commonly `new` / `open`).
- Add dedupe so the same notable is not sent repeatedly (for example by `finding_id` + timestamp window).

Unknown (environment-specific, confirm in your SOAR):

- Exact field carrying Splunk ES notable identifier (`event_id`, `finding_id`, `orig_sid`, etc.).
- Exact playbook launch event semantics in your Splunk SOAR app/integration.

## 2) Notable quality checklist before sending to analyzer

Before shipping to `INCOMING_DIR`, verify your notable contains at least:

- `summary` (required by analyzer contract)
- stable identifier (`notable_id` and/or `event_id` / `finding_id`)
- `search_name` (correlation search name/rule name)
- useful top-level context fields (`user`, `src_ip`, `dest_host`, etc.)

Important current analyzer behavior:

- Prompt formatting primarily consumes **top-level primitives/lists**.
- Nested objects may not be fully represented unless you also include a string field like `raw_event`.

So, when building payload:

- Keep high-value fields at top-level.
- Include full nested source as serialized `raw_event` string for audit/completeness.

## 3) Expected payload shape

Minimal recommended JSON per notable:

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

Notes:

- `supporting_events` is intentionally a list of strings (top-level list) for better prompt inclusion.
- One file = one notable.

## 4) Delivery method

Recommended delivery path:

- SOAR -> SFTP upload -> analyzer host `/incoming/<finding_id>.json`

Analyzer side watches only:

- `*.json`
- `*.txt`

## 5) Atomic upload consideration

Best practice is upload to `*.tmp` then rename to `*.json` to avoid partial reads.

The template keeps the flow simple (`upload file` action). If your SOAR SFTP app supports remote rename, add:

1. upload `name.json.tmp`
2. rename to `name.json`

If not supported, you can still run with direct `name.json`, but partial-read risk is higher.

## 6) Test plan (quick)

1. Manually run playbook on one known notable.
2. Verify file appears in analyzer incoming directory.
3. Verify analyzer moves file to processed/quarantine.
4. Verify report appears in `REPORT_DIR`.
5. Confirm writeback correlation still works via filename stem (`finding_id`).
