# GovCloud RAG Corpus Operations

This runbook covers source-document, ingestion, vector-index, and retrieval
operations for the `us-gov-east-1` deployment. The GovCloud production path
does not depend on Amazon Bedrock Knowledge Bases or S3 Vectors.

## Architecture

```text
approved source documents + manifest in versioned S3
    -> SQS ingestion queue
    -> ingestion Lambda
    -> Bedrock Titan embeddings
    -> tenant-scoped OpenSearch index
    -> bounded retrieval with S3 provenance
```

One VPC-only Amazon OpenSearch Service domain hosts separate indexes for:

| Lane | Used by | Content |
| --- | --- | --- |
| General SOC | Initial alert analysis and optional chat context | SOPs, runbooks, detection notes, escalation and pivot guidance |
| Splunk/SIEM dictionary | SPL generation | Indexes, sourcetypes, fields, CIM models, macros, lookups, approved SPL examples |
| Elasticsearch dictionary | Query DSL generation | Index patterns, fields, timestamp rules, approved examples |
| Case chunks | Selected-case chat | Generated alert/analysis chunks with canonical case provenance |

S3 is authoritative. OpenSearch is a rebuildable retrieval projection. DynamoDB
stores transactional case/import status but is not a vector store.

## Security Boundary

- OpenSearch is VPC-only and encrypted with the customer-configured KMS key.
- Provision the domain before enabling RAG in SAM — see
  [`../deployment/OPENSEARCH_PROVISIONING.md`](../deployment/OPENSEARCH_PROVISIONING.md).
- Runtime access uses IAM/SigV4; do not store OpenSearch credentials.
- Every document and query is scoped by the deployment/tenant identifier.
- Case retrieval additionally requires an exact `case_id` filter.
- Source documents must not contain credentials, private keys, tokens, or raw authentication headers.
- Retrieved operational guidance is advisory and cannot become alert evidence by itself.

## Source Layout

Use the customer-configured RAG source bucket and prefix. Keep one approved
corpus lane per sub-prefix and enable S3 versioning.

```text
rag-sources/
  soc/
  splunk/
  elastic/
  manifests/
```

Each ingestion job identifies:

- schema version
- deployment/tenant identifier
- corpus lane and corpus version
- source bucket, full key, version ID, ETag, and checksum
- embedding model and dimensions
- operation: create/update, delete, or rebuild

Unsupported file types, oversized documents, malformed manifests, tenant
mismatches, and checksum mismatches are terminal validation failures and go to
the ingestion DLQ after bounded handling.

When `IMAGE_INGEST_ENABLED=true` on the ingestion Lambda, manifests may also
include bounded PDF, DOCX, PNG, JPEG, GIF, and WebP sources. Text extraction
uses `pypdf` or `pdfminer.six` for PDFs, `python-docx` or ZIP/XML fallback for
DOCX, and either Amazon Textract (`IMAGE_INGEST_USE_TEXTRACT=true`) or a bounded
Pillow metadata placeholder for raster images. Defaults keep image ingest
disabled until operators explicitly enable it in SAM.

## Ingestion Behavior

1. Validate the queue job and source-object identity.
2. Read the exact S3 version named by the job.
3. Parse and create bounded deterministic chunks.
4. Generate embeddings with the configured GovCloud Bedrock embedding model.
5. Ensure the corpus index has the required k-NN mapping.
6. Tombstone prior active chunks for each source key.
7. Bulk-index deterministic replacement documents with source provenance.
8. Reconcile expected and actual chunk IDs before promotion.
9. Record ingestion status and metrics.

The idempotency key is the deployment/tenant, corpus lane, source version, and
checksum. Replaying a completed job must not create duplicate active chunks.

## Splunk Dictionary Content

Keep dictionary sections small and retrieval-oriented. Include only values
approved for generated investigation queries:

- `index=` names and purpose
- sourcetypes and event categories
- fields, types, aliases, and normalized join keys
- CIM data models and datasets
- approved macros and their required arguments
- lookup names, key fields, output fields, and freshness expectations
- bounded example SPL
- detection/search identifiers and applicable data sources
- content owner, effective version, and review date

The runtime policy allowlists remain authoritative. Retrieved content can narrow
or supply approved tokens but cannot override denied commands, time ranges, row
caps, field allowlists, or index restrictions.

## Reconciliation

Run reconciliation after ingestion failures, source deletion, index recovery,
or deployment upgrades. It compares the active S3 manifest with OpenSearch and:

- republishes missing source versions
- removes or tombstones orphaned chunks
- detects chunks produced by the wrong embedding model or dimensions
- verifies tenant, corpus, source, and case filters
- leaves the prior complete corpus active until replacement succeeds

Do not repair individual vectors manually in OpenSearch.

## Failure And Redrive

- Retry transient S3, Bedrock, OpenSearch, and network failures through SQS.
- Send exhausted jobs to the ingestion DLQ and alarm on any visible message.
- Correct the cause and run reconciliation before redrive.
- Redrive only the matching queue job; never copy arbitrary DLQ bodies directly into Lambda.
- A failed optional corpus leaves analysis available with an explicit degraded RAG status.
- A failed case embedding leaves case retrieval unavailable and visible as `pending` or `failed`.

## Customer Operationalization

Collect source ownership, approval workflow, source prefix, retention, embedding
model, OpenSearch capacity, KMS keys, VPC resources, and alarm destinations per
customer. See
[`../deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md`](../deployment/GOVCLOUD_CUSTOMER_CONFIGURATION.md).

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
