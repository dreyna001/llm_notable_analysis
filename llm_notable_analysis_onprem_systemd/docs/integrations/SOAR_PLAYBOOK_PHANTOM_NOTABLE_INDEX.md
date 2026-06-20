# SOAR Playbook (Splunk SOAR / Phantom) - Query Notable Index Pattern

This guide documents an **alternative** SOAR integration pattern where the
playbook queries Splunk ES for recent notables from the notable index, then
uploads one JSON payload per notable to the analyzer host.

Template code:

- `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_index_to_analyzer.py`

Container-triggered alternative (notable container plus artifact context):

- Guide: [`SOAR_PLAYBOOK_PHANTOM.md`](SOAR_PLAYBOOK_PHANTOM.md)
- Template: `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_to_analyzer.py`

## When to use this pattern

Use this pattern when:

- you want a scheduled or manual SOAR job that polls for recent notables
- your SOAR environment does not reliably launch on notable container creation
- you want the notable selection logic to live in a Splunk search

Use the container-triggered pattern when:

- SOAR already creates notable containers from Splunk ES
- you want to process the SOAR container plus its artifact context directly
- you need supporting events from SOAR artifacts in the payload

## Trigger timing

Run this playbook **after notables exist in Splunk ES**, not from raw events.

Recommended triggers:

- scheduled interval (for example every 5 to 15 minutes)
- manual operator run for backfill or testing

For scheduled/manual playbooks, the Phantom `container` passed to `on_start`
may be a thin control container rather than a notable container. The template
does not depend on notable container fields.

## Important behavior

- This pattern queries **`index=notable`** for recent rows.
- It uploads one file per notable to the analyzer's file-drop path.
- It does **not** bake Splunk credentials into the analyzer; credentials stay in SOAR.
- The template dedupes by sanitized `finding_id` **within one playbook run**.
  Cross-run dedupe still needs scheduling and/or SOAR state (see below).
- `supporting_events` is emitted as an empty list. Notable-index rows do not
  include SOAR artifact context unless you extend the template.

## Operator-tunable constants

Adjust these in the template before production use:

| Constant | Default | Purpose |
|----------|---------|---------|
| `SPLUNK_ASSET_NAME` | `splunk-es` | SOAR Splunk asset |
| `SPLUNK_QUERY_ACTION` | `run query` | Splunk query action name |
| `SFTP_ASSET_NAME` | `notable-analyzer-sftp` | SOAR SFTP asset |
| `SFTP_UPLOAD_ACTION` | `upload file` | SFTP upload action name |
| `SFTP_REMOTE_DIR` | `/incoming` | SFTP chroot drop directory |
| `LOOKBACK_MINUTES` | `15` | Relative Splunk lookback |
| `MAX_NOTABLES` | `100` | `head` limit |
| `PROCESS_STATUSES` | `new`, `open` | Notable states to retrieve |
| `QUERY_FIELDS` | see template | Fields kept by the search |

## Query semantics

The template builds a search like:

```spl
search index=notable earliest=-15m latest=now
| search (status="new" OR status="open")
| fields _time, event_id, finding_id, notable_id, search_name, rule_name, rule_title, summary, description, severity, urgency, owner, security_domain, status, risk_score, threat_category, orig_sid
| head 100
```

Adjust:

- lookback window (`LOOKBACK_MINUTES`)
- statuses (`PROCESS_STATUSES`)
- result limit (`MAX_NOTABLES`)
- field list (`QUERY_FIELDS`)
- index name if your environment differs

## Expected payload shape

Each uploaded file is `<finding_id>.json` with one normalized notable row.
The template maps Splunk fields into a flat analyzer-friendly JSON object:

```json
{
  "summary": "Suspicious Authentication Pattern",
  "notable_id": "123456",
  "event_id": "abc-123",
  "finding_id": "abc-123",
  "search_name": "Auth Rule",
  "risk_score": 80,
  "threat_category": "Credential Access",
  "alert_time": "2026-01-01T00:00:00Z",
  "severity": "high",
  "urgency": "medium",
  "status": "new",
  "owner": "unassigned",
  "security_domain": "access",
  "orig_sid": "1234567890.1",
  "supporting_events": [],
  "raw_event": "{\"finding_id\":\"abc-123\",\"summary\":\"...\"}",
  "ingest_source": "splunk_soar_phantom_notable_index"
}
```

Notes:

- `finding_id` in JSON and the filename stem are sanitized (alphanumeric,
  `-`, `_`; max 100 chars).
- Missing Splunk fields become `"unknown"` where the template cannot infer a value.
- `summary` falls back through `description`, `rule_title`, `rule_name`, and
  `search_name`.
- `raw_event` preserves the full notable-index row as a serialized string for
  audit and completeness.
- The analyzer accepts arbitrary JSON in `INCOMING_DIR`; see
  [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md)
  for correlation and writeback guidance.

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

## Dedupe and scheduling

This pattern should not blindly re-send the same notables forever.

Built-in within one run:

- duplicate rows with the same sanitized `finding_id` are skipped

Recommended cross-run controls:

- schedule the playbook at a short interval (for example every 5 to 15 minutes)
- limit query window overlap
- track already-sent `finding_id` / `event_id` values in SOAR state if needed

Exact state-tracking options are environment-specific and therefore **unknown**.

## Result-shape warning

Phantom action result formats vary by installed Splunk app.

Before production use, confirm:

- action name for running the query (`SPLUNK_QUERY_ACTION`)
- parameter name used to pass the SPL (`query` in the template)
- result payload shape (`data`, `action_results`, or app-specific structure)

The template parser handles top-level `data` lists and nested
`action_results[].data` lists. It may still need adjustment for your app.

## Test plan (quick)

1. Run the template unit tests from repo root:
   `PYTHONPATH=llm_notable_analysis_onprem_systemd/src python -m unittest discover -s llm_notable_analysis_onprem_systemd/tests/soar_playbook -p "test*.py" -v`
2. Manually run the playbook against a known notable window in a lab SOAR tenant.
3. Verify files appear under host `INCOMING_DIR`.
4. Verify the analyzer moves files to processed or quarantine.
5. Verify reports appear in `REPORT_DIR`.
6. Confirm Splunk writeback correlation still works via filename stem (`finding_id`).

## Related docs

- [`SOAR_PLAYBOOK_PHANTOM.md`](SOAR_PLAYBOOK_PHANTOM.md) - container-triggered pattern
- [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) - ingest contract and retention
- [`../operations/deployment/INSTALL.md`](../operations/deployment/INSTALL.md) - SFTP chroot and authorized_keys setup
