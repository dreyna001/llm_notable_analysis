# SOAR Playbook (Splunk SOAR / Phantom) - Query Notable Index Pattern

This guide documents an **alternative** SOAR integration pattern where the
playbook queries Splunk ES for recent notables from the notable index, then
uploads one JSON payload per notable to the analyzer host.

Template code:

- `llm_notable_analysis_onprem_systemd/soar_playbook/phantom_notable_index_to_analyzer.py`

## When to use this pattern

Use this pattern when:

- you want a scheduled or manual SOAR job that polls for recent notables
- your SOAR environment does not reliably launch on notable container creation
- you want the notable selection logic to live in a Splunk search

Use the existing container-triggered pattern when:

- SOAR already creates notable containers from Splunk ES
- you want to process the SOAR container plus its artifact context directly

## Important behavior

- This pattern queries **`index=notable`** for recent rows.
- It is still intended to run **after notables exist**, not from raw events.
- It uploads one file per notable to the analyzer's file-drop path.
- It does **not** bake Splunk credentials into the analyzer; credentials stay in SOAR.

## Query semantics

The template builds a search like:

```spl
search index=notable earliest=-15m latest=now
| search (status="new" OR status="open")
| fields _time, event_id, finding_id, notable_id, search_name, rule_name, rule_title, summary, description, severity, urgency, owner, security_domain, status, risk_score, threat_category, orig_sid
| head 100
```

Adjust:

- lookback window
- statuses
- result limit
- field list
- index name if your environment differs

## Delivery method

Recommended delivery path:

- SOAR -> SFTP upload -> analyzer host `/incoming/<finding_id>.json`

The same atomic upload guidance applies:

1. upload `name.json.tmp`
2. rename to `name.json`

## Dedupe and scheduling

This pattern should not blindly re-send the same notables forever.

Recommended controls:

- schedule the playbook at a short interval (for example every 5 to 15 minutes)
- limit query window overlap
- track already-sent `finding_id` / `event_id` values in SOAR state if needed

Exact state-tracking options are environment-specific and therefore **unknown**.

## Result-shape warning

Phantom action result formats vary by installed Splunk app.

Before production use, confirm:

- action name for running the query
- parameter name used to pass the SPL
- result payload shape (`data`, `action_results`, or app-specific structure)

The template contains a conservative parser but may still need adjustment.
