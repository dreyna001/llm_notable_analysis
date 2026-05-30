# AWS Operations Guide Index

Use this folder for customer-facing AWS operations decisions: which settings to
enable, what deployment parameters should differ by environment, and how to
validate a safe configuration without changing application code.

## Common Guide Shape

Area guides should generally use this pattern:

- **What This Controls**: the runtime behavior covered by the page.
- **Recommended Starting Posture**: conservative defaults for first rollout.
- **Customer Decisions**: questions operators must answer for each deployment.
- **Config Quick Reference**: relevant SAM/CloudFormation parameters and Lambda
  environment variables.
- **Validation And Rollout**: how to prove the configuration is safe.
- **Related Docs**: where to go for deeper deployment, architecture, or security
  context.

The guides are not feature specs. They help customers tune shipped behavior
within supported config bounds.

## Area Guides

The parity implementation will add the following guides alongside the existing
deployment image guide:

| Area | Guide | Purpose |
|------|-------|---------|
| LLM inference | `LLM_INFERENCE_OPERATIONS.md` | Bedrock model id, Lambda timeout, model-call budgets, and rollout. |
| Knowledge base content | `KNOWLEDGE_BASE_OPERATIONS.md` | Bedrock Knowledge Base ownership, source content, and lifecycle. |
| RAG retrieval | `RAG_OPERATIONS.md` | General SOC RAG enablement, failure mode, snippets, and context budgets. |
| SPL generation and execution | `SPL_OPERATIONS.md` | SPL generation, Bedrock KB grounding, Splunk REST/MCP execution policy. |
| Elasticsearch generation and execution | `ELASTICSEARCH_OPERATIONS.md` | Query DSL generation, Elastic grounding, `_search` execution policy. |
| Splunk writeback | `SPLUNK_WRITEBACK_OPERATIONS.md` | Optional notable comment writeback and idempotency. |
| ServiceNow | `SERVICENOW_OPERATIONS.md` | Incident draft/create, Secrets Manager token, and approval payload. |
| Security | `SECURITY_OPERATIONS.md` | IAM, secrets, TLS, endpoint validation, and action gates. |
| Testing | `../testing/TESTING.md` | Unit, smoke, and optional integration validation commands. |

## Current Diff 1 Status

Diff 1 creates the config/client foundation and this operations index. Detailed
area guides are created in the same implementation slices that introduce their
runtime behavior.
