# Compressed Input Handling Plan

Branch: `feature/s3-compressed-inputs`

**On-prem parity plan:** `llm_notable_analysis_onprem_systemd/docs/planning/COMPRESSED_INPUTS_PLAN.md`

## Goal

Allow the S3 notable pipeline to process compressed notable files uploaded under `incoming/` without changing the Bedrock analysis, markdown rendering, or sink routing contracts.

The smallest useful slice is single-file gzip support:

- `incoming/notable.json.gz`
- `incoming/notable.txt.gz`
- objects uploaded with S3 `ContentEncoding: gzip`

## In Scope

- Decompress gzip input before existing JSON/text normalization.
- Preserve current behavior for uncompressed `.json` and text uploads.
- Add bounded decompression to reduce gzip-bomb and oversized-payload risk.
- Produce clean output names, for example `incoming/notable.json.gz` -> `reports/notable.md`.
- Return clear per-record errors for malformed or unsupported compressed input.
- Add deterministic unit tests and update runtime documentation.

## Out Of Scope For First Pass

- ZIP archives.
- Multiple notables inside one uploaded object.
- Nested archives.
- New dependencies.
- Changes to Bedrock prompts, model configuration, IAM, or sink behavior.

## Design Notes

The current Lambda reads the S3 object body and immediately decodes it as UTF-8. Compressed bytes should be handled before UTF-8 decoding, then passed into the existing `normalize_notable()` flow.

Recommended implementation shape:

1. Add a small helper in `lambda_handler.py` that accepts the S3 key, object metadata/headers, and raw bytes.
2. Detect gzip via `.gz` suffix or `ContentEncoding: gzip`.
3. Decompress with Python stdlib `gzip`.
4. Enforce a configurable decompressed byte limit.
5. Decode decompressed bytes as UTF-8.
6. Derive content type from the inner filename, so `.json.gz` is treated as JSON.

## Acceptance Criteria

- Uncompressed `.json` and text files still process successfully.
- Valid `.json.gz` input is decompressed, parsed as JSON, analyzed, and written to the expected sink.
- Valid `.txt.gz` input is decompressed and treated as text.
- Malformed gzip input produces a clear error for that S3 record.
- Oversized decompressed input is rejected before Bedrock invocation.
- Output report names strip both the source extension and compression extension.
- Tests cover happy path, malformed gzip, oversized gzip, and unchanged uncompressed behavior.

## Planned Diffs

### Diff 1: Add Input Decoding Helper

Files:

- `src/s3_notable_pipeline/lambda_handler.py`
- `tests/test_lambda_handler.py`

Add helper functions for gzip detection, bounded decompression, UTF-8 decode, inner content-type detection, and output stem derivation.

Verification:

```bash
python -m unittest discover -s tests
```

### Diff 2: Wire Helper Into Lambda Handler

Files:

- `src/s3_notable_pipeline/lambda_handler.py`
- `tests/test_lambda_handler.py`

Replace direct `response['Body'].read().decode('utf-8')` with the helper while preserving existing analysis and sink flow.

Verification:

```bash
python -m unittest discover -s tests
```

### Diff 3: Document Runtime Contract

Files:

- `README.md`
- `docs/operations/DEPLOYMENT_IMAGE_STEPS.md`
- `deploy/aws/template-sam.yaml`
- `deploy/aws/template-cfn.yaml`

Document supported compressed formats, gzip-only first-pass scope, size-limit behavior, troubleshooting guidance, and the deployment parameter used to set the decompressed-size cap.

Verification:

```bash
python -m unittest discover -s tests
```

## Open Decision

Confirm whether gzip-only is sufficient for the first pass. If ZIP is required immediately, the plan should add stricter archive rules: max file count, allowed inner extensions, path traversal checks, nested archive rejection, and deterministic behavior for multi-file archives.
