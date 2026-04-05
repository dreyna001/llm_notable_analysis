# Recovery Behavior and Responsibilities

This document defines restart/recovery semantics for `llm_notable_analysis_onprem_systemd` and clarifies which reliability behavior is implemented by `onprem-llm-sdk` versus the notable-analysis application layer.

## Scope

- Deployment model: single-host service with file-drop ingest.
- Input queue location: `INCOMING_DIR`.
- Processing implementation: `onprem_service/onprem_main.py`, `onprem_service/ingest.py`, `onprem_service/local_llm_client.py`, `onprem_service/sinks.py`.
- Shared transport SDK: `onprem-llm-sdk/src/onprem_llm_sdk/`.

## Facts From Current Code

- Discovery only reads files currently present in `INCOMING_DIR` matching `*.json` or `*.txt` (`onprem_service/ingest.py`).
- Files are moved to `PROCESSED_DIR` only after the full processing path succeeds (`onprem_service/onprem_main.py`, `onprem_service/ingest.py`).
- Files are moved to `QUARANTINE_DIR` on known failures (`onprem_service/onprem_main.py`, `onprem_service/ingest.py`).
- The service does not maintain a persistent per-file checkpoint ledger.
- In concurrent mode, graceful shutdown waits for in-flight jobs to complete (`executor.shutdown(wait=True)` in `onprem_service/onprem_main.py`).

## Restart / Power Event Behavior Matrix

### 1) Graceful service stop/restart (`systemctl stop/restart`)

- **Idle state:** no work loss.
- **Sequential mode while processing one file:** signal sets shutdown flag, loop exits after current unit of work path returns.
- **Concurrent mode with in-flight jobs:** process waits for in-flight jobs to finish before exit.
- **Net effect:** best effort to finish currently running jobs before shutdown.

### 2) Host reboot/power loss while idle

- On restart, service re-scans `INCOMING_DIR` and processes remaining files.
- No special recovery step required.

### 3) Host reboot/power loss during LLM call or parsing

- Input file typically remains in `INCOMING_DIR` because move to `PROCESSED_DIR` has not happened yet.
- On restart, file is discovered and processed again.
- In-flight LLM HTTP call is not resumed mid-request (no checkpoint/resume protocol).

### 4) Host reboot/power loss after report write but before input move

- A report may already exist in `REPORT_DIR`.
- Input may still be in `INCOMING_DIR`.
- On restart, input can be reprocessed, producing another report file (collision suffix behavior in sink).

### 5) Host reboot/power loss after Splunk update but before input move

- Splunk writeback may already have been sent.
- Input may still be in `INCOMING_DIR`.
- On restart, input may be reprocessed and writeback may happen again.

### 6) Move operation interrupted by hard power cut

- Behavior depends on filesystem and exact cut timing.
- Expected practical outcome is either source still in `INCOMING_DIR` or destination in processed/quarantine.
- **Unknown:** strict atomic guarantees across all storage/backing configurations.

## What the SDK Does (and where)

Implemented in `onprem-llm-sdk/src/onprem_llm_sdk/`:

- **Config contract + validation:** `config.py`
  - Parses env vars and validates required numeric/boolean constraints.
- **Transport call execution:** `client.py`
  - Builds request payload, sends HTTP request, parses response text shape.
- **Per-process inflight guard:** `client.py`
  - `BoundedSemaphore` around requests (`_inflight_slot`).
- **SDK-native retry/backoff policy:** `client.py`
  - Retries timeout/transport/429/5xx based on `llm_max_retries`.
- **Error mapping:** `errors.py` + `client.py`
  - Maps failures into typed exceptions (`RequestTimeoutError`, `ServerError`, etc.).
- **Correlation/log/metrics hooks:** `client.py`, `logging.py`, `metrics.py`
  - Emits structured request success/failure events and metrics callbacks.

SDK does **not** implement persistent checkpointing, durable queue state, or crash-recovery replay control.

## What Notable Analysis Does (and where)

Implemented in `llm_notable_analysis_onprem_systemd/onprem_service/`:

- **Outer retry policy preserved for this app:** `local_llm_client.py`
  - App-level retry loop with existing backoff semantics.
  - SDK transport retries are explicitly disabled for this caller (`llm_max_retries=0`) to preserve prior behavior.
- **Prompt doctrine and domain instructions:** `local_llm_client.py`
- **Schema normalization/coercion/validation:** `local_llm_client.py`
- **Repair prompt flow for malformed outputs:** `local_llm_client.py`
- **TTP filtering/validation integration:** `local_llm_client.py` + `ttp_validator.py`
- **File lifecycle and movement:** `ingest.py` + `onprem_main.py`
- **Report write and Splunk writeback:** `sinks.py` + `onprem_main.py`

## Practical Implications

- The service is resumable at **file-level**, not at **mid-request checkpoint-level**.
- Duplicate processing is possible in specific crash windows (notably post-writeback/pre-move).
- This is acceptable for many queue-like pipelines but should be documented for ops and downstream consumers.

## Recommendations (non-breaking, optional)

- Ensure upstream uses atomic upload pattern (`.tmp` then rename) to avoid partial reads.
- If duplicate writeback is operationally sensitive, introduce idempotency controls at sink layer (for example, unique operation key per input file hash + finding ID).
- If strict exactly-once semantics are required, add a durable work ledger before/after side effects.

