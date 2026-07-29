# Image Ingest Prerequisites

Operators must stage OS packages, Python wheels, and retrieval model weights before
KB image ingest, portal chat image uploads, closed-ticket attachment processing, or
embedded images in PDF/DOCX sources can run on an air-gapped host.

Related: [`OFFLINE_PRESTAGE_GUIDE.md`](../deployment/OFFLINE_PRESTAGE_GUIDE.md),
[`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md),
[`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md),
[`CUSTOMER_DEFAULT_DEPLOYMENT.md`](../deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md).

## Scope

This workflow covers prerequisites **and** KB ingest runtime behavior for image/PDF/DOCX
embedded-image extraction. Closed-ticket attachment processing and portal chat images
use separate code paths but share the same prerequisite stack.

| Use case | What gets processed | Notes |
| --- | --- | --- |
| **KB images** | Operator-uploaded PNG/JPEG/GIF/WebP/PDF in KB source dirs | Indexed by `corpus_ingest` when `IMAGE_INGEST_ENABLED=true`; operator **delete-only** (no in-app edit) |
| **Portal chat images** | Analyst attaches an image to a chat question | Enable `CASE_QA_CHAT_IMAGES_ENABLED=true` on `portal.env`; **request-scoped only** — not persisted |
| **Closed-ticket attachments** | PNG/JPEG/GIF/WebP from ServiceNow sync | Vision path via Gemma 4 when `CLOSED_TICKET_VISION_ENABLED=true`; scanned PDFs use OCR |
| **PDF embedded images** | Raster pages in PDF KB sources | **pypdfium2 / PDFium only** (no alternate PDF backends); OCR via Tesseract |
| **DOCX embedded images** | Inline images in `.docx` KB sources | Body text unchanged; embedded images OCR'd into `Embedded Images OCR` sections |

There are **no runtime fallbacks** to alternate vision, OCR, PDF, or embedding stacks.
If a prerequisite is missing, extraction returns `prerequisite_missing` and the file is
**not** indexed as successful content (see `ingest_report.json` `extraction_status`).

## Runtime behavior (`corpus_ingest`)

When `IMAGE_INGEST_ENABLED=true` (customer-default `config.env.example`):

1. `setup_postgres_rag.sh` passes `--config-env` to `corpus_ingest`.
2. Standalone images and PDFs are OCR'd via the shared `extract_image_content` module.
3. DOCX files keep paragraph body text; embedded images are OCR'd separately.
4. Failed extractions appear in `ingest_report.json` under `warnings` and
   `extraction_status` — never silently indexed.
5. Rebuild is **full replace** per lane (same as text-only ingest): delete source file
   and rebuild to remove stale chunks.

Optional KB vision (`IMAGE_VISION_ENABLED=true`) adds advisory
`[Vision description (advisory)]` labels inside the shared OCR output for standalone
images, rendered PDF pages, and DOCX embedded images. `corpus_ingest` wires the
loopback Gemma vision callback automatically from `config.env` (inheriting
`LLM_API_URL` / `LLM_MODEL_NAME` / `LLM_API_TOKEN` when `IMAGE_VISION_*` fields are
empty). OCR remains the indexed source of truth; vision failures are recorded in
`ingest_report.json` `warnings` and extraction metadata without dropping OCR text.

Verify after rebuild:

```bash
sudo less /opt/llm-notable-analysis/knowledge_base/index/ingest_report.json
# Expect: image_ingest_enabled, extraction_status.indexed/failed, warnings
```

There are **no runtime fallbacks** to alternate vision, OCR, PDF, or embedding stacks.
If a prerequisite is missing, the corresponding path fails explicitly.

## Chosen stack (no fallbacks)

| Role | Component | License / lineage | Host notes |
| --- | --- | --- | --- |
| Vision (multimodal description) | **Gemma 4 31B** via **vLLM + LiteLLM** | Already installed by `scripts/install.sh` | Same gateway as analysis (`LLM_API_URL` / `LLM_MODEL_NAME`) |
| OCR (scanned text) | **Tesseract + Leptonica** | Apache 2.0; US lineage | System packages + language data staged offline |
| PDF rendering | **pypdfium2 / PDFium** | BSD-style (PDFium) | Python wheel in offline bundle |
| Image I/O | **Pillow** | HPND-style (Pillow) | Python wheel in offline bundle |
| DOCX | **python-docx** | MIT | Already in analyzer `requirements.txt` |
| Retrieval embedder | **IBM Granite** `ibm-granite/granite-embedding-english-r2` | Apache 2.0; US | Replaces Mixedbread; **768 dimensions** |
| Retrieval reranker | **IBM Granite** `ibm-granite/granite-embedding-reranker-english-r2` | Apache 2.0; US | Replaces Mixedbread reranker |

Apply Granite env defaults (does not overwrite live DSNs or secrets):

```bash
sudo bash scripts/configure_us_granite_retrieval_defaults.sh \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
```

## Two-phase workflow

### Phase 1 — Build bundle on a connected staging host

Run on a Linux host that matches the target OS/arch and Python 3.12 profile.
Uses the analyzer venv at `/opt/notable-analyzer/venv` for `pip` and Hugging Face
downloads when present (system `python3.12` often has no pip on production hosts).

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
bash scripts/build_image_ingest_offline_bundle.sh \
  --output-dir /mnt/staging/image-ingest-bundle
```

If the analyzer venv is elsewhere:

```bash
bash scripts/build_image_ingest_offline_bundle.sh \
  --output-dir /mnt/staging/image-ingest-bundle \
  --analyzer-venv /opt/notable-analyzer/venv
```

The bundle typically includes:

- Tesseract/Leptonica OS packages (or distro-specific `.deb`/`.rpm` set)
- Tesseract language packs approved for the deployment
- Python wheels: `pypdfium2`, `Pillow`, and transitive deps not already in the main wheelhouse
- IBM Granite embedding and reranker model trees for offline `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME`
- A manifest/checksum file for transfer verification

Transfer the bundle directory to the air-gapped target using local policy (removable
media, approved file transfer, etc.).

### Phase 2 — Install on the air-gapped target

After `scripts/install.sh` and Postgres/RAG setup:

```bash
cd /path/to/llm_notable_analysis_onprem_systemd
sudo bash scripts/install_image_ingest_prerequisites.sh \
  --bundle-dir /mnt/media/image-ingest-bundle
sudo bash scripts/configure_us_granite_retrieval_defaults.sh \
  --config-env /etc/notable-analyzer/config.env \
  --portal-env /etc/notable-analyzer/portal.env
```

Then rebuild KB and closed-ticket indexes if migrating from Mixedbread (see below).

## Verification

```bash
sudo bash scripts/verify_image_ingest_prerequisites.sh \
  --config-env /etc/notable-analyzer/config.env
```

The verify script checks, among other items:

- `tesseract` binary and expected language data
- Importable `pypdfium2`, `Pillow`, and `python-docx` in the analyzer venv
- Granite embed/rerank model paths under configured cache dirs
- Env alignment: `RAG_VECTOR_DIMENSIONS=768`, `CASE_QA_VECTOR_DIMENSIONS=768`, Granite model ids

Optional smoke after services are up:

```bash
sudo bash scripts/smoke_postgres_rag.sh --config-env /etc/notable-analyzer/config.env
sudo bash scripts/smoke_service_chain.sh --config-env /etc/notable-analyzer/config.env
```

## Granite 768-dim migration warning

Customer-default templates now use **IBM Granite** models at **768** vector dimensions.
This **replaces** the prior Mixedbread stack (`mixedbread-ai/mxbai-embed-large-v1` at
**1024** dimensions).

When changing embedder model or `RAG_VECTOR_DIMENSIONS`:

1. Update both analyzer `config.env` and portal `portal.env` (`CASE_QA_*` must match).
2. Run `configure_us_granite_retrieval_defaults.sh` or merge keys manually.
3. **Rebuild all KB lanes** (general SOC, SPL query, Elasticsearch grounding if used).
4. **Rebuild closed-ticket chunks** if closed-ticket RAG is enabled.
5. Confirm pgvector column dimensions match **768** (may require `setup_postgres_rag.sh`
   / schema migration per operator runbook).

Existing 1024-dim indexes are **not** compatible with 768-dim queries. Do not enable
retrieval until rebuild completes.

## Prompt and retention boundaries

### EXIF not included in prompts

Image metadata (EXIF: GPS, camera, timestamps, etc.) is **not** extracted or appended
to LLM prompts. Only decoded pixel content (and OCR text where applicable) feeds
vision/OCR steps.

### Portal chat: request-scoped, no persist

Chat-attached images are processed **only for the current request**. They are **not**
written to KB source directories, case archive blob storage, or closed-ticket attachment
paths. Operators should treat chat images as ephemeral analyst context.

### KB images: operator delete-only

KB image assets follow the same operator-controlled lifecycle as text sources: add via
approved upload/sync to source dirs, remove by deleting the file and rebuilding ingest.
There is no in-application image editor; corrections are **delete and re-upload**.

## Related docs

| Topic | Doc |
| --- | --- |
| Offline artifact staging | [`OFFLINE_PRESTAGE_GUIDE.md`](../deployment/OFFLINE_PRESTAGE_GUIDE.md) |
| KB source lifecycle | [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md) |
| Closed-ticket vision | [`SERVICENOW_CLOSED_TICKET_OPERATIONS.md`](../integrations/SERVICENOW_CLOSED_TICKET_OPERATIONS.md) |
| Customer-default env | [`CUSTOMER_DEFAULT_DEPLOYMENT.md`](../deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md) |
| RAG tuning | [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md) |
