# Recovery Behavior and Responsibilities

This document defines restart/recovery semantics for `llm_notable_analysis_onprem_systemd` and clarifies which reliability behavior is implemented by `onprem-llm-sdk` versus the notable-analysis application layer.

## What This Controls

This guide controls operational expectations when processing is interrupted: restart behavior, duplicate processing risk, report/writeback ordering, and who owns recovery tasks. It does not change runtime behavior.

## Recommended Starting Posture

- Keep the file-drop workflow simple and observable before enabling optional writebacks.
- Treat quarantine review as an operator responsibility.
- Validate restart behavior with a known-good file-drop smoke before production.
- Document who decides whether to replay or archive a failed input.

## Customer Decisions

- Who owns service restart, log review, and quarantine triage?
- Which artifacts are authoritative after partial failure: local report, Splunk comment, ServiceNow incident, or input file?
- What duplicate-processing risk is acceptable after host power loss?
- Who approves manual replay from `INCOMING_DIR` or `QUARANTINE_DIR`?

## Scope

- Deployment model: single-host service with file-drop ingest.
- Input queue location: `INCOMING_DIR`.
- Processing implementation: `onprem_main.py`, `ingest.py`, `local_llm_client.py`, `sinks.py`, `servicenow.py`, `idempotency.py`.
- Shared transport SDK: `onprem-llm-sdk/src/onprem_llm_sdk/`.

## Facts From Current Code

- Discovery reads only `*.json` and `*.txt` directly under `INCOMING_DIR` (no recursion), oldest mtime first (`ingest.py`).
- **Success boundary:** `move_to_processed()` runs only after the full `process_notable()` path completes without an early return or uncaught exception (`onprem_main.py`). Input leaves the queue at that point.
- **Quarantine triggers:** unreadable/oversized input, empty file, LLM response containing `"error"`, or any uncaught exception (`quarantine_after_failure()` / `move_to_quarantine()`). If quarantine move fails, the file may remain in `INCOMING_DIR` and be rediscovered.
- **Non-blocking side effects:** Splunk writeback errors, ServiceNow create errors, and case-archive failures are logged but do **not** quarantine the input or block `move_to_processed()`.
- **Processing order (one file):** LLM analysis -> optional investigation queries -> optional ServiceNow draft/create -> markdown/HTML reports -> optional case archive -> optional Splunk writeback -> move to processed.
- Local report/HTML writes use collision suffixes on filename clash (`sinks.py`); no idempotency markers for local files.
- The service does not maintain a per-file processing checkpoint ledger.
- **Side-effect idempotency (optional):** file-backed markers in `SIDE_EFFECT_IDEMPOTENCY_DIR` via `idempotency.py`. Default is off; the `action_gated` profile sets `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`. Applies only to external writes in `sinks.py` (Splunk) and `servicenow.py` (create), not LLM calls or local reports.
- In concurrent mode, graceful shutdown waits for in-flight jobs (`executor.shutdown(wait=True)`). Files discovered but not yet submitted stay in `INCOMING_DIR`.

## Restart / Power Event Behavior Matrix

### 1) Graceful service stop/restart (`systemctl stop/restart`)

- **Idle:** no work loss.
- **Sequential mode while processing one file:** shutdown flag stops the loop after the current file finishes.
- **Concurrent mode with in-flight jobs:** process waits for in-flight jobs before exit.
- **Net effect:** best effort to finish currently running jobs; unstarted files remain in `INCOMING_DIR`.

### 2) Host reboot/power loss while idle

- On restart, service re-scans `INCOMING_DIR` and processes remaining files.
- No special recovery step required.

### 3) Host reboot/power loss during LLM call or parsing

- Input typically remains in `INCOMING_DIR` because `move_to_processed()` has not run.
- On restart, the file is discovered and processed again from the start.
- In-flight LLM HTTP calls are not resumed mid-request.

### 4) Host reboot/power loss after report write but before input move

- A report may already exist in `REPORT_DIR` (and HTML/case archive may exist).
- Input may still be in `INCOMING_DIR`.
- On restart, input is reprocessed; local reports get a collision suffix if the base filename already exists.

### 5) Host reboot/power loss after Splunk writeback but before input move

- **Idempotency disabled (default):** Splunk may already have been updated; input may still be in `INCOMING_DIR`; restart reprocesses and may send duplicate writeback.
- **Idempotency enabled:** replay skips Splunk update when a completed marker exists for operation `splunk_notable_update` and key `finding_id` (input filename stem). **Crash window:** Splunk POST succeeded but marker was not persisted -> replay may duplicate writeback.

### 6) Host reboot/power loss after ServiceNow create but before input move

- Same pattern as Splunk: duplicate create possible when idempotency is off; skipped on replay when marker exists for operation `servicenow_incident_create` and key `correlation_id` or `correlation_display` from the draft payload.
- **Crash window:** create POST succeeded but marker was not persisted -> replay may create a duplicate incident.

### 7) Splunk or ServiceNow error logged, input still moved to processed

- Writeback/create failure returns an error status; processing still calls `move_to_processed()`.
- The input will **not** auto-retry unless an operator copies it back to `INCOMING_DIR` or `QUARANTINE_DIR`.

### 8) Move operation interrupted by hard power cut

- Behavior depends on filesystem and exact cut timing.
- Expected practical outcome: source still in `INCOMING_DIR`, or destination in `PROCESSED_DIR` / `QUARANTINE_DIR`, or in rare cases both/neither until operator review.
- **Unknown:** strict atomic guarantees across all storage/backing configurations.

## Side-Effect Idempotency and Replay

Implemented in `idempotency.py`, invoked from `sinks.py` and `servicenow.py`:

| Operation | Key | Replay when marker exists |
| --- | --- | --- |
| `splunk_notable_update` | `finding_id` (input filename stem) | Skip POST; return `status=skipped` |
| `servicenow_incident_create` | draft `correlation_id`, else `correlation_display` | Skip POST; return prior `sys_id`/`number` from marker metadata |

Mechanics:

- `begin_side_effect()` acquires a per-key lock (30s wait; stale lock cleared after 300s), skips when a marker file exists, or reserves execution when none exists.
- `complete_side_effect_success()` writes the marker after a successful external POST; failed POST releases the lock without writing a marker (safe to retry).
- Generic/missing keys raise `ValueError` when idempotency is enabled.
- Markers are pruned by retention housekeeping (`SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`).

Idempotency does **not** deduplicate LLM calls, local reports, input moves, or read-only investigation queries.

## What the SDK Does (and where)

Implemented in `onprem-llm-sdk/src/onprem_llm_sdk/`:

- **Config contract + validation:** `config.py`
- **Transport call execution:** `client.py`
- **Per-process inflight guard:** `client.py` (`BoundedSemaphore`)
- **SDK-native retry/backoff policy:** `client.py` (timeout/transport/429/5xx via `llm_max_retries`)
- **Error mapping:** `errors.py` + `client.py`
- **Correlation/log/metrics hooks:** `client.py`, `logging.py`, `metrics.py`

The SDK does **not** implement persistent checkpointing, durable queue state, or crash-recovery replay control.

## What Notable Analysis Does (and where)

Implemented in `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/onprem_service/`:

- **Outer retry policy:** `local_llm_client.py` (app-level retry loop; SDK transport retries disabled with `llm_max_retries=0`)
- **Prompt doctrine, schema validation, repair flow, TTP filtering:** `local_llm_client.py` + `ttp_validator.py`
- **File lifecycle:** `ingest.py` + `onprem_main.py`
- **Local reports and Splunk writeback:** `sinks.py` + `onprem_main.py`
- **ServiceNow draft/create:** `servicenow.py` + `onprem_main.py`
- **External side-effect dedupe:** `idempotency.py` (Splunk + ServiceNow create only)

## Practical Implications

- Recovery is **file-level**, not mid-request checkpoint-level.
- Duplicate LLM work and duplicate local reports are possible in crash windows before `move_to_processed()`.
- Duplicate Splunk/ServiceNow writes are possible when idempotency is off, or when idempotency is on but the crash happened after a successful POST and before marker persistence.
- Writeback/create failures do not leave the input in the queue; operator replay is manual.
- Acceptable for many queue-like pipelines; document downstream duplicate tolerance explicitly.

## Recommendations (non-breaking, optional)

- Use atomic upload upstream (`.tmp` then rename) to avoid partial reads.
- Enable `action_gated` (or set `SIDE_EFFECT_IDEMPOTENCY_ENABLED=true`) when duplicate Splunk/ServiceNow side effects are operationally sensitive.
- If strict exactly-once semantics are required end-to-end, add a durable work ledger that spans LLM, local artifacts, and external writes.

## Next

- Enable safe writebacks: [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md) (`action_gated`)
- File-drop behavior: [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md)
- Post-restart validation: [`../../testing/TESTING.md`](../../testing/TESTING.md) (`smoke_service_chain.sh`)
