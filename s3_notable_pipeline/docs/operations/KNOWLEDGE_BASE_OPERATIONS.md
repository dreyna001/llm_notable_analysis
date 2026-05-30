# AWS Knowledge Base Operations

## What This Controls

Bedrock Knowledge Bases provide advisory retrieval context for AWS parity
features. Diff 2 uses one general SOC Knowledge Base for `rag`. Later diffs add
separate Knowledge Bases for SPL and Elasticsearch grounding.

## Recommended Starting Posture

- Keep Knowledge Base content small, curated, and owned.
- Include SOPs, escalation guidance, field dictionaries, detection notes, and
  runbooks that analysts already trust.
- Do not load current-alert facts into the advisory Knowledge Base.

## Customer Decisions

- Which team owns source document approval and refresh cadence?
- Which documents are allowed to influence model synthesis?
- What retention and deletion process applies to removed guidance?
- Are separate Knowledge Bases required for general SOC guidance, SPL grounding,
  and Elasticsearch grounding?

## Config Quick Reference

| Purpose | Parameter / env |
|---------|------------------|
| General SOC RAG | `RagBedrockKbId` / `RAG_BEDROCK_KB_ID` |
| SPL grounding | planned `SPLQueryRagBedrockKbId` / `SPL_QUERY_RAG_BEDROCK_KB_ID` |
| Elastic grounding | planned `ElasticsearchGroundingBedrockKbId` / `ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID` |

Knowledge Base ids are set through SAM/CloudFormation parameters. The templates
populate Lambda environment variables and IAM permissions.

## Validation And Rollout

1. Verify the Knowledge Base is queryable in the AWS account and region.
2. Confirm the Lambda role has `bedrock:Retrieve` only for the configured
   Knowledge Base ARN.
3. Run a known notable with `rag` enabled and verify retrieved context is
   advisory in model behavior and metadata.
4. Remove or correct stale source documents before production rollout.

## Related Docs

- `RAG_OPERATIONS.md`
- `SECURITY_OPERATIONS.md`
