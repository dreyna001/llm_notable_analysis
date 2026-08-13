# Commercial AWS RAG Retrieval Operations

The `rag` capability adds bounded advisory context from the deployment's private
OpenSearch SOC corpus before the main alert-analysis Bedrock call.

## Analysis Use

General SOC retrieval runs before initial analysis and may inform:

- competing benign and adversary hypotheses
- evidence gaps
- analyst pivots
- recommended validation and escalation actions

It may not create direct evidence, IOCs, verdict facts, or ATT&CK evidence. The
alert remains the authoritative source for those fields.

Splunk/SIEM and Elasticsearch dictionaries are separate retrieval lanes used
only during query generation. Selected-case chat uses case chunks and may add
general SOC guidance as a separately labeled advisory lane.

## Runtime Contract

- Backend: `RAG_RETRIEVAL_BACKEND=opensearch` for commercial production.
- Scope: `RAG_TENANT_ID` is required and attached to every write and query.
- Endpoint: `OPENSEARCH_ENDPOINT` is HTTPS, VPC-only, and IAM/SigV4 protected.
- Indexes: case, SOC, Splunk dictionary, and optional Elastic dictionary are separate.
- Query size and rendered context are bounded by lane-specific top-k and character budgets.
- Retrieval metadata records corpus version, chunk IDs, source versions, scores, and embedding model.
- Failure defaults to explicit degraded/suppressed behavior for advisory context; core case retrieval reports unavailable rather than inventing an answer.

Legacy `bedrock_kb` selection exists only for explicit compatibility testing.
It is not the production fallback in `us-east-1`; adopting it as the default
requires a separate security, provenance, cost, and operational review.

## Rollout

1. Deploy core processing with RAG profiles disabled.
2. Provision and validate the private OpenSearch domain — see
   [`../deployment/OPENSEARCH_PROVISIONING.md`](../deployment/OPENSEARCH_PROVISIONING.md).
3. Ingest and approve one corpus lane at a time.
4. Enable `rag`, then the selected investigation profile, in staging.
5. Confirm retrieval attribution and evidence separation in JSON reports.
6. Promote the same corpus manifest, image digest, and settings through the customer release process.

See [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md) for ingestion,
reconciliation, deletion, and redrive procedures.
