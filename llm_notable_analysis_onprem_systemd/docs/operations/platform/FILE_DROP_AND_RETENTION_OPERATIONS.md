# File Drop And Retention Operations

This guide helps customers tune the file-drop workflow, runtime directories,
polling, retention, and local concurrency settings without changing code.

Settings live in `/etc/notable-analyzer/config.env` (see `config.env.example` in
the package root).

## What This Controls

The analyzer watches `INCOMING_DIR`, discovers top-level `*.json` and `*.txt`
files (non-recursive), processes them oldest-first, writes reports to
`REPORT_DIR`, then moves inputs to `PROCESSED_DIR` or `QUARANTINE_DIR`. Reports
are markdown by default; when the `html_reports` profile is selected, a static
`.html` dashboard is written next to the `.md` report.

Retention is two-stage (`retention.py`):

1. Move aged files from live dirs into `ARCHIVE_DIR` subdirs (`processed/`,
   `quarantine/`, `reports/`).
2. Delete files from those archive subdirs after `ARCHIVE_RETENTION_DAYS`.

Retention runs on `RETENTION_RUN_INTERVAL_SECONDS` inside the analyzer main loop
and again via the optional `notable-retention.timer` systemd unit (daily).

When the `analyst_portal` profile is enabled, retention also deletes expired
Postgres case rows (derived `case_chunks` cascade), and expired portal chat
sessions when `CASE_QA_CHAT_HISTORY_ENABLED=true`.

## AWS Parity Notes

| Topic | On-prem today | AWS (`s3_notable_pipeline`) |
| --- | --- | --- |
| Gzip notables | **Planned** — not discovered by `ingest.py` | **Implemented** — `.gz`/`.gzip` suffix or S3 `ContentEncoding: gzip` |
| Input size cap | `MAX_INPUT_FILE_BYTES` (default `4194304`) on raw `.json`/`.txt` | `MaxDecompressedInputBytes` (default `1048576`) on uncompressed and decompressed payloads |
| Retention mechanism | Filesystem move-to-archive then delete; Postgres case/chat cleanup | S3 lifecycle + DynamoDB TTL (no archive dir) |

Gzip parity target: single-payload `*.json.gz`, `*.txt.gz`, and `.gzip` suffix
variants with bounded decompression and `MAX_DECOMPRESSED_INPUT_BYTES` default
`1048576`. That variable is **not** in `config.env.example` yet. Until gzip
ships on-prem, do not drop `.gz` files into `INCOMING_DIR`.

AWS reference:
[`s3_notable_pipeline/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../../../../s3_notable_pipeline/docs/operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md).

## Recommended Starting Posture

- Keep `INGEST_MODE=file_drop`; it is the only supported ingest mode.
- Keep runtime paths under `/var/notables` unless the host has an approved layout
  (defaults below).
- Keep `CAPABILITY_PROFILES=core` until operators accept the HTML dashboard
  format; then add `html_reports`.
- Keep `POLL_INTERVAL=5` until file-drop volume is measured.
- Start sequentially: `CONCURRENCY_ENABLED=false`, `MAX_WORKERS=1`,
  `MAX_QUEUE_DEPTH=8`.
- Keep `INPUT_RETENTION_DAYS=2`, `REPORT_RETENTION_DAYS=7`,
  `ARCHIVE_RETENTION_DAYS=14`, and `RETENTION_RUN_INTERVAL_SECONDS=86400` until
  audit needs are agreed.

### Default runtime paths (`config.env.example`)

| Variable | Default |
| --- | --- |
| `INCOMING_DIR` | `/var/notables/incoming` |
| `PROCESSED_DIR` | `/var/notables/processed` |
| `QUARANTINE_DIR` | `/var/notables/quarantine` |
| `REPORT_DIR` | `/var/notables/reports` |
| `ARCHIVE_DIR` | `/var/notables/archive` |
| `SIDE_EFFECT_IDEMPOTENCY_DIR` | `/var/notables/idempotency` (when `action_gated` writes are enabled) |

## Customer Decisions

### What should SOAR or operators drop?

The analyzer processes top-level `*.json` or `*.txt` in `INCOMING_DIR` only.
Symlinks are rejected. Oversized files (above `MAX_INPUT_FILE_BYTES`, default
`4194304`) are quarantined before read.

- JSON is preferred: the file should contain a UTF-8 JSON object.
- Text is supported as a fallback: the full file contents are treated as raw
  alert text.
- For JSON payloads, include at least a clear `summary`.
- Strongly preferred fields for correlation and writeback are `notable_id`,
  `event_id`, `finding_id`, `search_name`, `alert_time`, `risk_score`,
  `threat_category`, and any raw event context the customer is allowed to send.
- Report output names use the **filename stem** first; confirm the stem maps to
  the intended Splunk `finding_id` or customer-equivalent notable identifier
  when Splunk writeback is enabled.

Recommended delivery behavior: upload to a temporary filename that does not
match `*.json` or `*.txt`, then atomically rename to the final file after upload
completes. This avoids partial reads.

### Where should files live?

**Settings:** `INCOMING_DIR`, `PROCESSED_DIR`, `QUARANTINE_DIR`, `REPORT_DIR`,
`ARCHIVE_DIR`, `CAPABILITY_PROFILES`

- Keep all runtime outputs off the source tree.
- Ensure directories match systemd `ReadWritePaths` (typically `/var/notables`).
- If SFTP chroot is used, validate ownership and symlink behavior after install.
- Size storage for peak incoming volume, generated `.md` and optional `.html`
  reports, quarantined files, and archive retention.

### How quickly should the service poll?

**Setting:** `POLL_INTERVAL` (default `5` seconds)

- Lower values reduce latency but create more filesystem wakeups.
- Higher values reduce overhead and suit batch-style drops.
- Keep polling aligned with SOAR/SFTP delivery cadence.

### Which transport should deliver files?

The default and recommended transport is SOAR-to-analyzer SFTP into the chroot
created by the installer. NFS can work when it is already an approved enterprise
pattern, but it has more permission, network, and audit complexity. Use the
SOAR/Phantom guides in [`../../integrations/`](../../integrations/) for playbook
patterns.

### How long should evidence and reports stay?

**Settings:** `INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`,
`ARCHIVE_RETENTION_DAYS`, `CASE_RETENTION_DAYS`, `CASE_QA_CHAT_HISTORY_RETENTION_DAYS`,
`SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`, `RETENTION_RUN_INTERVAL_SECONDS`

- `INPUT_RETENTION_DAYS` (default `2`): move aged files from `PROCESSED_DIR` and
  `QUARANTINE_DIR` into `ARCHIVE_DIR/processed/` and `ARCHIVE_DIR/quarantine/`.
- `REPORT_RETENTION_DAYS` (default `7`): move aged reports into
  `ARCHIVE_DIR/reports/`.
- `ARCHIVE_RETENTION_DAYS` (default `14`): delete files from archive subdirs
  (mtime reset on archive move counts time **in archive**, not since creation).
- With `analyst_portal`, `CASE_RETENTION_DAYS` (default `30`) controls Postgres
  case row expiry; derived `case_chunks` rows delete by cascade.
- With `CASE_QA_CHAT_HISTORY_ENABLED=true`, `CASE_QA_CHAT_HISTORY_RETENTION_DAYS`
  (default `7`) controls portal chat session expiry.
- With side-effect writes enabled, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`
  (default `30`) deletes markers under `SIDE_EFFECT_IDEMPOTENCY_DIR` directly
  (not archived).
- Align windows with incident evidence, privacy, and storage policies.
- Document who owns exports if reports must be preserved elsewhere.

### Should processing be concurrent?

**Settings:** `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH`

Defaults: `CONCURRENCY_ENABLED=false`, `MAX_WORKERS=1`, `MAX_QUEUE_DEPTH=8`.

- Start with concurrency off (one notable at a time).
- When enabled, processing uses a `ThreadPoolExecutor` with backpressure: at
  `MAX_QUEUE_DEPTH` in-flight jobs, new files wait until the next poll cycle.
- After load tests on A6000-class GPUs with gemma-4-31B-it, try
  `MAX_WORKERS=2` and `MAX_QUEUE_DEPTH=16` only if vLLM latency and GPU headroom
  allow.
- Increase workers only after measuring LLM latency, GPU load, Splunk load, and
  RAG database behavior.

## Config Quick Reference

| Area | Primary variables | Package defaults |
| --- | --- | --- |
| Ingest | `INGEST_MODE`, `POLL_INTERVAL` | `file_drop`, `5` |
| Input size (today) | `MAX_INPUT_FILE_BYTES` | `4194304` (4 MiB; quarantine if larger) |
| Input size (planned gzip) | `MAX_INPUT_FILE_BYTES`, `MAX_DECOMPRESSED_INPUT_BYTES` | decompressed cap target `1048576` (AWS-aligned; not in config yet) |
| Runtime paths | `INCOMING_DIR`, `PROCESSED_DIR`, `QUARANTINE_DIR`, `REPORT_DIR`, `ARCHIVE_DIR` | under `/var/notables/` |
| Retention | `INPUT_RETENTION_DAYS`, `REPORT_RETENTION_DAYS`, `ARCHIVE_RETENTION_DAYS`, `RETENTION_RUN_INTERVAL_SECONDS` | `2`, `7`, `14`, `86400` |
| Case archive | `CASE_RETENTION_DAYS`, `CASE_QA_CHAT_HISTORY_RETENTION_DAYS` | `30`, `7` (chat when enabled) |
| Side-effect idempotency | `SIDE_EFFECT_IDEMPOTENCY_DIR`, `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` | `/var/notables/idempotency`, `30` |
| Concurrency | `CONCURRENCY_ENABLED`, `MAX_WORKERS`, `MAX_QUEUE_DEPTH` | `false`, `1`, `8` |
| Payload correlation | Filename stem, `finding_id`, `event_id`, `notable_id` in incoming JSON | stem wins for report naming |

## Validation And Rollout

1. Confirm directory ownership and permissions after install.
2. Drop a known-good JSON notable into `INCOMING_DIR`.
3. Confirm report creation, input movement to `PROCESSED_DIR`, and no unexpected
   quarantine.
4. Drop a malformed or oversize file and confirm quarantine behavior.
5. Run retention in a lab or with aged fixture files before lowering production
   retention.
6. Enable concurrency only after baseline sequential behavior is stable.

## Reset Server-Side Application Data

Use [`../../../scripts/reset_onprem_app_data.sh`](../../../scripts/reset_onprem_app_data.sh)
to return the installed app to an empty server-side state without reinstalling
the stack.

The script clears:

- all tables in the configured `CASE_POSTGRES_SCHEMA`, including cases, derived
  case chunks, chat sessions, and chat messages;
- optional `notable_dispositions` tables when that schema exists; and
- contents of `INCOMING_DIR`, `PROCESSED_DIR`, `QUARANTINE_DIR`, `REPORT_DIR`,
  `ARCHIVE_DIR`, and `SIDE_EFFECT_IDEMPOTENCY_DIR`.

The script explicitly preserves PostgreSQL RAG schemas, SQLite/FAISS indexes,
knowledge-base source/index directories, models, caches, code, configuration,
credentials, and TLS material. Browser-local portal storage is outside the VM
and is not cleared; clear site data in the browser separately when a fully empty
client view is required.

Preview the exact targets without changing data:

```bash
sudo bash scripts/reset_onprem_app_data.sh
```

Execute with a timestamped recovery backup and exact interactive confirmation:

```bash
sudo bash scripts/reset_onprem_app_data.sh --execute
```

For approved non-interactive automation:

```bash
sudo bash scripts/reset_onprem_app_data.sh --execute --yes
```

`--skip-backup` is available only with `--execute` and should be reserved for
disposable environments. The script stops affected analyzer, portal, retention,
and disposition-sync units, restores only units that were active beforehand,
and does not restart vLLM, LiteLLM, PostgreSQL, or nginx.

## Related Docs

- [`INSTALL.md`](../deployment/INSTALL.md)
- [`../../integrations/SOAR_PLAYBOOK_PHANTOM.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM.md)
- [`../../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md`](../../integrations/SOAR_PLAYBOOK_PHANTOM_NOTABLE_INDEX.md)
- [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md)
- [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md)
- [`SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
