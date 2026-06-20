# SOAR Playbook (Splunk SOAR / Phantom)

This guide provides a minimal **container-triggered** playbook pattern for
environments where:

- SOAR orchestrates notable handling.
- `llm_notable_analysis_onprem_systemd` consumes dropped `*.json` / `*.txt` files.
- The file should contain one notable plus supporting artifact context from SOAR.

Template code:

- `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_to_analyzer.py`

Alternative guide/template for scheduled notable-index polling:

- Guide: [`SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md)
- Template: `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_index_to_analyzer.py`

## When to use this pattern

Use this pattern when:

- SOAR already creates notable containers from Splunk ES
- you want to process the SOAR container plus artifact CEF context directly
- playbook launch on notable container creation/update is reliable in your tenant

Use the notable-index polling pattern when:

- you want a scheduled or manual SOAR job that queries `index=notable`
- container-triggered launch is unreliable
- you accept flat notable-index rows without SOAR artifact context (unless you extend that template)

## Trigger timing

Run this playbook **after the notable exists from the correlation search
pipeline**, not from raw events.

Important clarification:

- This document describes the **container-triggered** pattern.
- The template does **not** directly run an `index=notable` query.
- For notable-index polling, use the alternative guide/template above.

Recommended trigger gates:

- trigger on notable container creation/update in SOAR (`label=notable` in most deployments)
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

## Operator-tunable constants

Adjust these in the template before production use:

| Constant | Default | Purpose |
|----------|---------|---------|
| `SFTP_ASSET_NAME` | `notable-analyzer-sftp` | SOAR SFTP asset |
| `SFTP_UPLOAD_ACTION` | `upload file` | SFTP upload action name |
| `SFTP_REMOTE_DIR` | `/incoming` | SFTP chroot drop directory |
| `MAX_SUPPORTING_EVENTS` | `500` | Artifact rows collected via `phantom.collect2` |
| `PROCESS_LABELS` | `notable` | Allowed container labels; empty set allows all |
| `PROCESS_STATUSES` | `new`, `open` | Allowed container statuses; empty set allows all |
| `PROCESS_SEVERITIES` | `medium`, `high`, `critical` | Allowed severities; empty set allows all |

Also validate SFTP action parameter keys (`vault_id`, `remote_path`, `file_name`)
against your installed SFTP app.

## Finding ID and filename

The template chooses `finding_id` in this order:

1. container `source_data_identifier` (often maps to upstream Splunk notable id)
2. container `id`
3. `"unknown"` fallback

Both JSON `finding_id` and the remote filename stem are sanitized (alphanumeric,
`-`, `_`; max 100 chars) before upload as `<finding_id>.json`.

If Splunk writeback is enabled, confirm that filename stem maps to the intended
Splunk `finding_id` or customer-equivalent notable identifier.

## Expected payload shape (template default)

The template is intentionally **format-agnostic**. It does not remap container
fields into a flat Splunk-notable schema. Each uploaded file is
`<finding_id>.json` with one JSON object like:

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
- One file = one notable container.

## Analyzer ingest behavior

The analyzer accepts arbitrary JSON (or plain text) in `INCOMING_DIR`. For
`.json` files it passes the submitted JSON content to the LLM as-is, including
nested objects such as `container` and `cef`.

Strongly preferred fields for correlation, portal facets, and Splunk writeback
are documented in
[`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md).
Include a clear summary or equivalent human-readable context when you can.

Optional payload enhancements (not emitted by the default template):

- add top-level `summary`, `search_name`, `alert_time`, `risk_score`, or
  `threat_category` if you extend `_build_payload`
- add a serialized `raw_event` string if you want an explicit audit blob in
  addition to nested JSON

## Delivery method

Recommended delivery path:

- SOAR -> SFTP upload -> analyzer SFTP chroot `/incoming/<finding_id>.json`

On a default install, that chroot path maps to host `INCOMING_DIR`
(`/var/notables/incoming`, symlinked from `/var/sftp/soar/incoming`).

The analyzer watches only `*.json` and `*.txt` in `INCOMING_DIR`.

## Atomic upload consideration

Best practice is upload to `*.tmp` then rename to `*.json` to avoid partial reads.

The template keeps the flow simple (direct `<finding_id>.json` upload). If your
SOAR SFTP app supports remote rename, add:

1. upload `name.json.tmp`
2. rename to `name.json`

If not supported, you can still run with direct `name.json`, but partial-read
risk is higher.

## Test plan (quick)

1. Manually run the playbook on one known notable container in a lab SOAR tenant.
2. Confirm routing gates (`label`, `status`, `severity`) behave as expected.
3. Verify the file appears under host `INCOMING_DIR`.
4. Verify the analyzer moves the file to processed or quarantine.
5. Verify reports appear in `REPORT_DIR`.
6. Confirm Splunk writeback correlation still works via filename stem (`finding_id`).

For the notable-index template unit tests, see
[`SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md).

## Related docs

- [`SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md) - scheduled `index=notable` polling pattern
- [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) - ingest contract and retention
- [`../operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md) - SFTP chroot and authorized_keys setup
