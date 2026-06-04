# File Drop And Retention Operations

This guide helps customers tune the file-drop workflow, runtime directories,
polling, retention, and local concurrency settings without changing code.

## What This Controls

The analyzer watches an incoming directory, processes supported files, writes
reports, then moves inputs to processed or quarantine paths. Reports are
markdown by default; when the `html_reports` profile is selected, a static
`.html` dashboard is written next to the `.md` report in `REPORT_DIR`.
Retention settings archive and later delete older runtime artifacts.

## Recommended Starting Posture

- Keep `INGEST_MODE=file_drop`; it is the supported ingest mode.
- Keep runtime paths under `/var/notables` unless the host has an approved
  storage layout.
- Keep `CAPABILITY_PROFILES=core` until operators have accepted the HTML
  dashboard format; then add `html_reports`.
- Keep `POLL_INTERVAL=5` until file-drop volume is measured.
- Start sequentially: `CONCURRENCY_ENABLED=false`, `MAX_WORKERS=1`.
- Use conservative retention values until audit and evidence needs are agreed.

## Customer Decisions

### What should SOAR or operators drop?

The analyzer processes files matching `*.json` or `*.txt` in `INCOMING_DIR`.

**Planned (AWS parity):** single-payload gzip notables (`*.json.gz`, `*.txt.gz`,
and `.gzip` suffix variants) with bounded decompression and the same
`MAX_DECOMPRESSED_INPUT_BYTES` default (`1048576`) as
`s3_notable_pipeline`. See
[`../planning/COMPRESSED_INPUTS_PLAN.md`](../planning/COMPRESSED_INPUTS_PLAN.md).
Until that ships, do not drop `.gz` files into `INCOMING_DIR`; they will not be
discovered.

- JSON is preferred: the file should contain a UTF-8 JSON object.
- Text is supported as a fallback: the full file contents are treated as raw
  alert text.
- For JSON payloads, include at least a clear `summary`.
- Strongly preferred fields for correlation and writeback are `notable_id`,
  `event_id`, `finding_id`, `search_name`, `alert_time`, `risk_score`,
  `threat_category`, and any raw event context the customer is allowed to send.
- If Splunk writeback is enabled, confirm the filename stem maps to the
  intended Splunk `finding_id` or customer-equivalent notable identifier.

Recommended delivery behavior: upload to a temporary filename that does not
match `*.json` or `*.txt`, then atomically rename to the final file after upload
completes. This avoids partial reads.

### Where should files live?

**Settings:** `INCOMING_DIR`, `PROCESSED_DIR`, `QUARANTINE_DIR`, `REPORT_DIR`,
`ARCHIVE_DIR`, `CAPABILITY_PROFILES`

- Keep all runtime outputs off the source tree.
- Ensure directories match systemd `ReadWritePaths`.
- If SFTP chroot is used, validate ownership and symlink behavior after install.
- Size storage for peak incoming volume, generated `.md` and optional `.html`
  reports, quarantined files, and archive retention.

### How quickly should the service poll?

**Setting:** `POLL_INTERVAL`

- Lower values reduce latency but create more filesystem wakeups.
- Higher values reduce overhead and are easier for batch-style drops.
- Keep polling aligned with SOAR/SFTP delivery cadence.

### Which transport should deliver files?

The default and recommended transport is SOAR-to-analyzer SFTP into the chroot
created by the installer. NFS can work when it is already an approved enterprise
pattern, but it has more permission, network, and audit complexity. Use the
SOAR/Phantom guides in [`../integrations/`](../integrations/) for playbook
patterns.

### How long should evidence and reports stay?

**Settings:** `INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`,
`ARCHIVE_RETENTION_DAYS`, `RETENTION_RUN_INTERVAL_SECONDS`

- Align with incident evidence, privacy, and storage policies.
- Keep quarantine long enough for operator review.
- Make sure archive delete timing is acceptable before production.
- Document who owns exports if reports must be preserved elsewhere.

### Should processing be concurrent?

**Settings:** `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH`

- Start with concurrency off.
- Increase workers only after measuring LLM latency, GPU load, Splunk load, and
  RAG database behavior.
- Use `MAX_QUEUE_DEPTH` to avoid unbounded pending work during spikes.

## Config Quick Reference

| Area | Primary variables |
|------|-------------------|
| Ingest | `INGEST_MODE`, `POLL_INTERVAL` |
| Input size (today) | `MAX_INPUT_FILE_BYTES` (on-disk cap for `.json` / `.txt`) |
| Input size (planned gzip parity) | `MAX_INPUT_FILE_BYTES` (compressed on-disk cap), `MAX_DECOMPRESSED_INPUT_BYTES` (decompressed UTF-8 cap; AWS default `1048576`) |
| Runtime paths | `INCOMING_DIR`, `PROCESSED_DIR`, `QUARANTINE_DIR`, `REPORT_DIR`, `ARCHIVE_DIR`, `CAPABILITY_PROFILES` |
| Retention | `INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`, `ARCHIVE_RETENTION_DAYS`, `RETENTION_RUN_INTERVAL_SECONDS` |
| Concurrency | `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH` |
| Payload correlation | Filename stem, `finding_id`, `event_id`, `notable_id` in incoming JSON |

## Validation And Rollout

1. Confirm directory ownership and permissions after install.
2. Drop a known-good JSON notable into `INCOMING_DIR`.
3. Confirm report creation, input movement, and no unexpected quarantine.
4. Drop a malformed file and confirm quarantine behavior.
5. Run retention in a lab or with aged fixture files before lowering
   production retention.
6. Enable concurrency only after baseline sequential behavior is stable.

## Related Docs

- [`INSTALL.md`](INSTALL.md)
- [`../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../integrations/SOAR_PLAYBOOK_PHANTOM.md)
- [`../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)
- [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md)
- [`../planning/COMPRESSED_INPUTS_PLAN.md`](../planning/COMPRESSED_INPUTS_PLAN.md) (planned gzip intake)

