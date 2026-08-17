# Commercial AWS RAG Corpus Operations

Canonical runbook for RAG source documents, ingestion, vector indexes, and corpus
lifecycle on commercial `us-east-1`. Runtime retrieval tuning lives in
[`RAG_OPERATIONS.md`](RAG_OPERATIONS.md); OpenSearch domain provisioning in
[`../deployment/OPENSEARCH_PROVISIONING.md`](../deployment/OPENSEARCH_PROVISIONING.md).

Commercial v1 uses application-managed OpenSearch retrieval (not S3 Vectors).
Bedrock Knowledge Bases are an optional compatibility backend, not the production default.

## Architecture

```text
approved source documents + manifest in versioned S3
    -> SQS ingestion queue -> ingestion Lambda -> Bedrock Titan embeddings
    -> tenant-scoped OpenSearch index -> bounded retrieval with S3 provenance
```

One VPC-only OpenSearch domain hosts separate indexes:

| Lane | Used by | Content |
| --- | --- | --- |
| General SOC | Initial alert analysis and optional chat context | SOPs, runbooks, detection notes, escalation and pivot guidance |
| Splunk/SIEM dictionary | SPL generation | Indexes, sourcetypes, fields, CIM models, macros, lookups, approved SPL examples |
| Elasticsearch dictionary | Query DSL generation | Index patterns, fields, timestamp rules, approved examples |
| Case chunks | Selected-case chat | Generated alert/analysis chunks with canonical case provenance |

S3 is authoritative. OpenSearch is a rebuildable retrieval projection. DynamoDB
stores transactional case/import status but is not a vector store.

## Security Boundary

- OpenSearch is VPC-only, KMS-encrypted; access via IAM/SigV4 only (no stored credentials).
- Every document and query is scoped by the deployment/tenant identifier (`RagTenantId`).
- Case retrieval additionally requires an exact `case_id` filter.
- Source documents must not contain credentials, private keys, tokens, or raw auth headers.
- Retrieved guidance is advisory and cannot become alert evidence by itself.
- Runtime policy allowlists remain authoritative over retrieved dictionary content.

## Source Layout

Use the customer-configured RAG source bucket and prefix. One approved corpus
lane per sub-prefix; enable S3 versioning.

When `RagSourceBucketName` is set, configure that bucket to send
`s3:ObjectCreated:*` events under `RagManifestPrefix` to the stack's
`RagIngestionQueueArn` output. Leave blank to have the stack wire manifest
notifications from its managed input bucket.

```text
rag-sources/
  soc/
  splunk/
  elastic/
  manifests/
```

Each ingestion job identifies: schema version, deployment/tenant identifier,
corpus lane and version, source bucket/key/version ID/ETag/checksum, embedding
model and dimensions, and operation (create/update, delete, or rebuild).

Unsupported file types, oversized documents, malformed manifests, tenant
mismatches, and checksum mismatches are terminal validation failures and go to
the ingestion DLQ after bounded handling.

## Ingestion Behavior

Validate job and source identity; read the exact S3 version; chunk deterministically;
embed with the configured Bedrock model; ensure k-NN mapping; tombstone prior
active chunks; bulk-index replacements with provenance; reconcile chunk IDs;
record status and metrics.

Idempotency key: deployment/tenant, corpus lane, source version, and checksum.
Replaying a completed job must not create duplicate active chunks.

## Splunk Dictionary Content

Keep sections small and retrieval-oriented. Include only values approved for
generated investigation queries: `index=` names, sourcetypes, fields and aliases,
CIM models, approved macros, lookups, bounded example SPL, detection identifiers,
and content owner/version/review date.

## Reconciliation

Run after ingestion failures, source deletion, index recovery, or deployment
upgrades. Compares active S3 manifest with OpenSearch: republish missing versions,
tombstone orphans, detect wrong embedding model/dimensions, verify tenant/corpus/
source/case filters; leave prior complete corpus active until replacement succeeds.
Do not repair individual vectors manually in OpenSearch.

## Failure And Redrive

- Retry transient S3, Bedrock, OpenSearch, and network failures through SQS.
- Send exhausted jobs to the ingestion DLQ; alarm on any visible message.
- Correct the cause and run reconciliation before redrive.
- Redrive only the matching queue job; never copy arbitrary DLQ bodies into Lambda.
- Failed optional corpus: analysis continues with explicit degraded RAG status.
- Failed case embedding: case retrieval unavailable as `pending` or `failed`.

## Customer Operationalization

Collect source ownership, approval workflow, prefix, retention, embedding model,
OpenSearch capacity, KMS keys, VPC resources, and alarm destinations per customer.
See [`../deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](../deployment/COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md).

## Validation

Corpus-level checks (infra preflight: [`../../testing/TESTING.md`](../../testing/TESTING.md)
OpenSearch preflight table):

1. Upload a versioned representative source document and manifest.
2. Confirm the ingestion queue drains and no DLQ message appears.
3. Verify indexed documents contain correct tenant, corpus, source version, and embedding model.
4. Retrieve a known query; confirm bounded, attributed results.
5. Update and delete the source; verify stale chunks are no longer active.
6. Replay the original job; verify no duplicate active chunks.
7. **Negative:** cross-tenant and cross-case queries return no documents.
8. Exercise Bedrock throttling and OpenSearch outage; verify retries, alarms, and redrive.

## Deploy path — next

- **Path B (step 11):** [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md) and [`../../../frontend/analyst-portal/README.md`](../../../frontend/analyst-portal/README.md)
