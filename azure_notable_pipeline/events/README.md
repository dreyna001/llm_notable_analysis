# Native Azure trigger fixtures

Phase 1 includes polling Blob-trigger and Storage Queue samples. The intake
wrapper authors a strict v1 analyzer job with exactly `schema_version`,
`container_name`, `blob_name`, `etag`, `size_bytes`, and `last_modified`.
Fixtures must use native Azure trigger values and normalized internal jobs; AWS
event envelopes are intentionally excluded.

- `blob-trigger-observation.json` is the native property set observed by the
  polling Blob-trigger wrapper.
- `analyzer-job.v1.json` is the exact application-authored queue payload.
