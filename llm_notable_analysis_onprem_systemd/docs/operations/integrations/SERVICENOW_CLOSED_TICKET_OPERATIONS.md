# ServiceNow Closed Ticket RAG (On-Prem)

Read-only sync of closed security tickets into Postgres, hybrid chunk indexing, and
advisory retrieval for first-pass alert analysis and analyst portal chat.

## One-time setup

1. Apply Postgres schema (included in case archive setup):

   ```bash
   sudo bash scripts/setup_postgres_case_archive.sh \
     --config-env /etc/notable-analyzer/config.env \
     --portal-env /etc/notable-analyzer/portal.env
   ```

   This creates `notable_closed_tickets` tables, grants the analyzer role write access,
   and grants the portal role **read-only** `SELECT` on closed-ticket tables.

2. Configure analyzer `config.env` (see `config.env.example`):

   - `CLOSED_TICKET_RAG_ENABLED=true` for retrieval/indexing
   - `SERVICENOW_CLOSED_TICKET_SYNC_ENABLED=true` plus token, table, and encoded query
   - `CLOSED_TICKET_RETENTION_DAYS` — **30, 60, or 90** (default **30**)
   - `CASE_POSTGRES_DSN` — same database as case archive

3. Configure portal `portal.env` for chat lane:

   - `CLOSED_TICKET_RAG_ENABLED=true`
   - `CASE_QA_CLOSED_TICKET_ENABLED=true`
   - Same `CLOSED_TICKET_POSTGRES_SCHEMA` / chunks table as analyzer

4. Install operator scripts (or full `scripts/install.sh`):

   - `/opt/notable-analyzer/scripts/run_closed_ticket_sync.py`
   - `/opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py`

5. Enable timer (not auto-enabled by install):

   ```bash
   sudo systemctl enable --now notable-closed-ticket-sync.timer
   ```

## Daily operation

- **Raw sync:** `notable-closed-ticket-sync.service` (timer ~04:30) pulls tickets,
  journals, and optional attachments into `notable_closed_tickets.servicenow_tickets`.
- **Auto-index:** When `CLOSED_TICKET_RAG_ENABLED=true`, the sync script indexes up to
  **500** pending/failed tickets per run (`index_status` in `pending` or `failed`,
  active and unexpired only). Raw sync alone does not index when RAG is disabled.
  Index failures are logged and recorded on the sync summary without rolling back a
  successful raw sync; the operator script exits non-zero when indexing fails so
  systemd can retry indexing on the next timer run without re-pulling unchanged data.
- **Retention:** Each sync run purges tickets whose `expires_at` has passed. Retention
  is measured from `closed_at` (+ 30/60/90 days), falling back to `source_updated_at`
  or sync time when closure is unavailable. Attachment files under
  `CLOSED_TICKET_ATTACHMENT_DIR` are removed only after the purge transaction commits.

Manual sync:

```bash
/opt/notable-analyzer/venv/bin/python /opt/notable-analyzer/scripts/run_closed_ticket_sync.py
```

## Image attachments (vision and OCR)

General SOC **KB ingest does not index standalone image files** until the text+image
pipeline is enabled; see [`../rag/IMAGE_INGEST_PREREQUISITES.md`](../rag/IMAGE_INGEST_PREREQUISITES.md).

For **closed-ticket** attachments:

- **Raster images** (PNG/JPEG/GIF/WebP): when `CLOSED_TICKET_VISION_ENABLED=true`,
  the shared extraction module calls **Gemma 4 31B** on the same OpenAI-compatible
  gateway as analysis (`LLM_API_URL` / `LLM_MODEL_NAME`, via LiteLLM and vLLM).
  Empty `CLOSED_TICKET_VISION_API_BASE`, `_MODEL`, and `_API_KEY` inherit those LLM
  settings at startup. Vision is advisory; OCR text is preserved when vision fails
  (`vision_failed`, `vision_partial`, or per-raster warnings in extraction metadata).
- **Scanned PDFs and image-only pages**: OCR via **Tesseract** plus optional per-page
  advisory vision through the same shared extraction path (after
  `install_image_ingest_prerequisites.sh`); no alternate PDF or OCR backends.
- **DOCX embedded images**: OCR and optional vision for embedded rasters via the shared
  extractor; bounds inherit `IMAGE_INGEST_*` when set, with
  `CLOSED_TICKET_ATTACHMENT_MAX_BYTES` / `_MAX_TEXT_CHARS` overrides retained.

Customer-default enablement (preserves secrets and DSNs):

```bash
sudo bash scripts/configure_closed_ticket_vision_defaults.sh \
  --config-env /etc/notable-analyzer/config.env
sudo systemctl restart notable-analyzer
```

PDF attachments use **pypdfium2/PDFium** for page rasterization when prerequisites are
installed; vision is not applied to vector PDF text. Text/json/csv attachments decode
without vision or OCR.

Validate multimodal chat before production sync (replace token and use a small PNG):

```bash
source /etc/notable-analyzer/config.env
IMG_B64="$(printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==' | tr -d '\n')"
curl -fsS "${LLM_API_URL%/chat/completions}/chat/completions" \
  -H "Authorization: Bearer ${LLM_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"${LLM_MODEL_NAME}\",\"max_tokens\":64,\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"text\",\"text\":\"What color is this image? One word.\"},{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/png;base64,${IMG_B64}\"}}]}]}"
```

If the call fails, check `journalctl -u vllm` and LiteLLM model support for
`image_url` on your vLLM build; indexing still proceeds with OCR text and explicit
`vision_failed` / `vision_partial` extraction statuses (never silent vision success).

## Status verification

```sql
SELECT index_status, count(*)
FROM notable_closed_tickets.servicenow_tickets
WHERE is_active = true AND expires_at > now()
GROUP BY 1
ORDER BY 1;

SELECT count(*) FROM notable_closed_tickets.ticket_chunks;
```

Analyzer metadata on first-pass reports `closed_ticket_rag_*` fields. Portal chat
logs retrieval errors when Postgres or embedding fails (lane stays fail-soft).

## Full chunk rebuild

After schema/model changes or backfill:

```bash
/opt/notable-analyzer/venv/bin/python \
  /opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py \
  --config-env /etc/notable-analyzer/config.env \
  --all --batch-size 100
```

Single ticket:

```bash
/opt/notable-analyzer/venv/bin/python \
  /opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py \
  --config-env /etc/notable-analyzer/config.env \
  --ticket-id <sys_id>
```

Dry-run (no writes):

```bash
/opt/notable-analyzer/venv/bin/python \
  /opt/notable-analyzer/scripts/rebuild_closed_ticket_chunks.py \
  --dry-run --all --batch-size 20
```

## Retention

`CLOSED_TICKET_RETENTION_DAYS` sets `expires_at` on upsert. Retrieval and incremental
indexing ignore inactive or expired tickets. Raw rows remain until separately purged.

## Next

- Path B step 7: [`../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md`](../analyst_portal/ANALYST_PORTAL_NETWORK_DEPLOYMENT.md)
- Path B step 9: [`../../testing/TESTING.md`](../../testing/TESTING.md) — chat closed-ticket lane after sync
- Path order: root [`README.md`](../../../README.md#2-deploy--pick-one-path) section 2
