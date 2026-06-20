# AWS Knowledge Base Operations

This runbook covers **content lifecycle** for Amazon Bedrock Knowledge Bases
used by the S3 notable pipeline. Retrieval size, failure modes, and snippet
budgets are in [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md).

## What This Controls

Bedrock Knowledge Bases provide advisory retrieval context. The pipeline does
**not** create, ingest, or sync Knowledge Bases. Operators provision KBs and
data sources outside the SAM/CloudFormation stack, then pass Knowledge Base IDs
into deploy parameters.

There are three supported KB content lanes:

| Lane | Prompt block | Capability profile | When retrieval runs |
|------|--------------|--------------------|---------------------|
| General SOC RAG | `SOC_OPERATIONAL_CONTEXT` | `rag` | Main notable analysis |
| SPL query grounding | `SPL_QUERY_GROUNDING_CONTEXT` | `spl_readonly` (with KB id set) | SPL generation call |
| Elasticsearch query grounding | `ELASTICSEARCH_GROUNDING_CONTEXT` | `elastic_readonly` (with KB id set) | Query DSL generation call |

Splunk and Elastic grounding KBs are separate from each other and from the
general SOC KB. Do not load current-alert facts into any advisory KB.

## Recommended Starting Posture

- Keep Knowledge Base content small, curated, and owned.
- Include SOPs, escalation guidance, field dictionaries, detection notes, and
  runbooks that analysts already trust.
- Use **separate** Bedrock Knowledge Bases for general SOC guidance, SPL
  grounding, and Elasticsearch grounding.
- Do not enable `rag`, `spl_readonly`, or `elastic_readonly` until source
  documents are approved and an initial ingestion job has completed.
- Do not store secrets, tokens, raw auth headers, or private keys in KB source
  documents.

## Customer Decisions

- Which team owns source document approval and refresh cadence?
- Which documents are allowed to influence model synthesis?
- Which Bedrock embedding model and vector store back each Knowledge Base?
- Which S3 bucket and prefix hold approved source documents for each lane?
- What retention and deletion process applies to removed guidance?
- Are separate Knowledge Bases required for general SOC guidance, SPL grounding,
  and Elasticsearch grounding? (Recommended: yes.)

## Runtime Contract

The deployment templates (`deploy/aws/template-sam.yaml`,
`deploy/aws/template-cfn.yaml`) wire Knowledge Base IDs into Lambda environment
variables and grant `bedrock:Retrieve` **only** for configured Knowledge Base
ARNs when the corresponding parameter is non-empty.

Lambda calls `bedrock-agent-runtime:Retrieve` at analysis time. It does **not**:

- create or delete Knowledge Bases or data sources
- start or monitor ingestion jobs
- write back to KB source buckets

General SOC retrieval uses alert text as the query. SPL and Elasticsearch
grounding retrieval uses alert text plus competing hypotheses (see
`spl_query_grounding.py` and `elasticsearch_query_grounding.py`).

Rendered snippets include source labels from result metadata. The runtime reads,
in order: `source_file`, `source`, `uri`, `title`, and for grounding lanes
`section_path` or `section`. When metadata is missing, labels fall back to
Bedrock location fields or `bedrock_kb`.

## Provision A Knowledge Base (Customer-Managed)

Perform these steps in the target AWS account and region **before** enabling a
profile that depends on the KB.

1. **Create a Bedrock Knowledge Base** in the Amazon Bedrock console or via API.
   Choose an embedding model approved for that account and region (for example
   `amazon.titan-embed-text-v2:0`).
2. **Attach a vector store** (for example OpenSearch Serverless). Vector store
   choice and sizing are customer-managed; the pipeline templates do not
   provision it.
3. **Add an S3 data source** pointing at an operator-controlled bucket prefix
   for curated source documents. Block public access and encrypt at rest.
4. **Run an initial ingestion (sync) job** and wait until the job status is
   complete.
5. **Record the Knowledge Base ID** (for example `ABCDEFGHIJ`) for deploy
   parameters.
6. **Repeat for each lane** that needs grounding. Use one KB per lane; do not
   mix SOC SOPs with Splunk index catalogs or Elastic field maps in the same KB.

## Add Or Update Source Documents

1. Stage approved changes in operator source control (outside the pipeline
   stack).
2. Upload or update objects in the S3 prefix configured for the Knowledge Base
   data source. Prefer short, clearly headed `.txt` or `.md` files; Bedrock also
   supports other formats allowed by the chosen data source configuration.
3. Start a new **Sync** or **Full** ingestion job for that data source in the
   Bedrock console or with `StartIngestionJob`.
4. Wait for the job to complete before validating in production traffic.
5. For general SOC RAG, redeploy is **not** required when only source documents
   change. Redeploy **is** required when changing Knowledge Base IDs or when
   adding a new KB parameter to the stack.

### General SOC KB

Use for broad triage SOPs, escalation runbooks, and detection notes. Do not put
Splunk index catalogs or Elastic field maps here.

### SPL query KB

Use for customer-specific Splunk environment facts: `index=`, `sourcetype=`,
field dictionaries, macro names, and approved example SPL. Keep one log source
or hunt pattern per section so retrieval can return atomic token blocks.

Detailed onboarding: [`../investigation/SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md).

### Elasticsearch query KB

Use for index patterns, ECS or custom field dictionaries, timestamp conventions,
and approved bool/filter Query DSL examples. Documented hunt fields must also
appear in `ELASTICSEARCH_ALLOWED_FIELDS` at deploy time; the KB supplements
but does not replace config allowlists.

Detailed onboarding:
[`../investigation/ELASTICSEARCH_OPERATIONS.md`](../investigation/ELASTICSEARCH_OPERATIONS.md).

## Rollback And Retirement

To roll back a bad content update:

1. Restore the prior approved object set in the S3 data source prefix from
   operator backup or source control.
2. Run a new ingestion job for that data source.
3. Process a representative notable and confirm retrieved snippets cite expected
   sources in JSON metadata or CloudWatch logs.
4. Redeploy only if the Knowledge Base ID itself changed.

To retire guidance, remove or replace objects in S3 and resync. Do not leave
stale documents in the active prefix.

## Config Quick Reference

Set Knowledge Base IDs through SAM/CloudFormation parameters. The templates
populate Lambda environment variables and scoped IAM permissions.

| Purpose | SAM / CloudFormation parameter | Lambda env var | Auto-enables |
|---------|-------------------------------|----------------|--------------|
| General SOC RAG | `RagBedrockKbId` | `RAG_BEDROCK_KB_ID` | Retrieve IAM when id non-empty; retrieval when `rag` profile (or `RagEnabled=true`) and id set |
| SPL grounding | `SplQueryRagBedrockKbId` | `SPL_QUERY_RAG_BEDROCK_KB_ID` | `SPL_QUERY_RAG_ENABLED=true` when id non-empty |
| Elastic grounding | `ElasticsearchGroundingBedrockKbId` | `ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID` | `ELASTICSEARCH_GROUNDING_ENABLED=true` when id non-empty |

General SOC enablement also requires `CapabilityProfiles=core,rag` (sets
`RAG_ENABLED=true` via profile) or `RagEnabled=true` when the `rag` profile is
not listed. SPL and Elastic grounding require their respective investigation
profiles (`spl_readonly` or `elastic_readonly`) for the generation path to run.

Do not manually edit Lambda environment variables in the console as the normal
workflow.

## Validation And Rollout

1. Verify each Knowledge Base is queryable in the target account and region
   (Bedrock console test retrieve or `aws bedrock-agent-runtime retrieve`).
2. Confirm the Lambda execution role has `bedrock:Retrieve` only for configured
   Knowledge Base ARNs (granted when the matching parameter is non-empty).
3. Deploy with `CapabilityProfiles=core` first; confirm base markdown/JSON
   output.
4. Enable one profile at a time in a non-production stack:
   - `rag` with `RagBedrockKbId`
   - `spl_readonly` with optional `SplQueryRagBedrockKbId`
   - `elastic_readonly` with optional `ElasticsearchGroundingBedrockKbId`
     (never together with `spl_readonly`)
5. Run a known notable and verify:
   - General RAG: JSON `metadata.rag_status` is `success` or `no_match`; model
     behavior treats retrieved text as advisory, not alert evidence.
   - SPL grounding: generated SPL uses grounded tokens when alert type matches
     KB content; metadata records grounding status.
   - Elastic grounding: generated Query DSL respects allowlists and grounded
     index/field tokens.
6. Remove or correct stale source documents and resync before production
   rollout.

Smoke guidance: [`../../testing/TESTING.md`](../../testing/TESTING.md).

## Related Docs

- [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md) — retrieval enablement, failure modes, snippet budgets
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md) — profile bundles and rollout order
- [`../investigation/SPL_OPERATIONS.md`](../investigation/SPL_OPERATIONS.md) — SPL generation, execution, Splunk onboarding
- [`../investigation/ELASTICSEARCH_OPERATIONS.md`](../investigation/ELASTICSEARCH_OPERATIONS.md) — Query DSL generation and Elastic onboarding
- [`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md) — Bedrock model and Lambda sizing
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md) — IAM, secrets, and data handling
