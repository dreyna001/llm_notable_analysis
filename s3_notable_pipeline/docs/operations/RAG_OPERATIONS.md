# AWS RAG Operations

## What This Controls

The `rag` capability profile adds advisory SOC context from an Amazon Bedrock
Knowledge Base before the base notable-analysis call. Retrieved content is
rendered as `SOC_OPERATIONAL_CONTEXT` and is not direct alert evidence.

## Recommended Starting Posture

- Keep `CAPABILITY_PROFILES=core` for first deployment.
- Enable `rag` only after the Knowledge Base source documents are curated and
  approved by the customer.
- Use `RagFailureMode=suppress` for first rollout so analysis can continue if
  retrieval is unavailable.

## Customer Decisions

- Which Bedrock Knowledge Base contains approved SOC SOPs, escalation guidance,
  field dictionaries, detection notes, and runbooks?
- Who owns source document freshness and removal?
- Should retrieval failures suppress context or fail the analysis?

## Config Quick Reference

| Area | Parameter / env |
|------|------------------|
| Enablement | `CapabilityProfiles=core,rag`, `RagEnabled=true` |
| Knowledge Base | `RagBedrockKbId` / `RAG_BEDROCK_KB_ID` |
| Retrieval size | `RagMaxSnippets`, `RagContextBudgetChars` |
| Failure behavior | `RagFailureMode=suppress|fail_closed` |

Set Bedrock Knowledge Base ids through SAM/CloudFormation parameters. Do not
manually edit Lambda environment variables in the console as the normal workflow.

## Validation And Rollout

1. Deploy with `core` and verify markdown/JSON output still works.
2. Populate and approve the Bedrock Knowledge Base.
3. Deploy with `CapabilityProfiles=core,rag`, `RagEnabled=true`, and
   `RagBedrockKbId=<kb-id>`.
4. Confirm CloudWatch logs show retrieval status and generated JSON metadata has
   `rag_status` and `rag_snippet_count`.
5. Review report quality and verify the model does not treat retrieved SOP text
   as observed alert facts.

## Related Docs

- `KNOWLEDGE_BASE_OPERATIONS.md`
- `LLM_INFERENCE_OPERATIONS.md`
- `SECURITY_OPERATIONS.md`
