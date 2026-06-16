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

| Area | Guide | Purpose |
|------|-------|---------|
| Capability profiles | [`CAPABILITY_PROFILES.md`](CAPABILITY_PROFILES.md) | Supported AWS feature bundles and profile-first configuration. |
| LLM inference | [`LLM_INFERENCE_OPERATIONS.md`](LLM_INFERENCE_OPERATIONS.md) | Bedrock model id, Lambda timeout, model-call budgets, and rollout. |
| Knowledge base content | [`KNOWLEDGE_BASE_OPERATIONS.md`](KNOWLEDGE_BASE_OPERATIONS.md) | Bedrock Knowledge Base ownership, source content, and lifecycle. |
| RAG retrieval | [`RAG_OPERATIONS.md`](RAG_OPERATIONS.md) | General SOC RAG enablement, failure mode, snippets, and context budgets. |
| SPL generation and execution | [`SPL_OPERATIONS.md`](SPL_OPERATIONS.md) | SPL generation, Bedrock KB grounding, Splunk REST/MCP execution policy. |
| Elasticsearch generation and execution | [`ELASTICSEARCH_OPERATIONS.md`](ELASTICSEARCH_OPERATIONS.md) | Query DSL generation, Elastic grounding, `_search` execution policy. |
| Splunk writeback | [`SPLUNK_WRITEBACK_OPERATIONS.md`](SPLUNK_WRITEBACK_OPERATIONS.md) | Optional notable comment writeback and idempotency. |
| ServiceNow | [`SERVICENOW_OPERATIONS.md`](SERVICENOW_OPERATIONS.md) | Incident draft/create, Secrets Manager token, and approval payload. |
| Analyst portal | [`ANALYST_PORTAL_OPERATIONS.md`](ANALYST_PORTAL_OPERATIONS.md) | S3 case archive, DynamoDB CaseIndex, JWT portal API, static SPA, and pinned-case Q&A. |
| S3 intake and retention | [`FILE_DROP_AND_RETENTION_OPERATIONS.md`](FILE_DROP_AND_RETENTION_OPERATIONS.md) | S3 prefixes, gzip handling, lifecycle rules, size limits, and report outputs. |
| Security | [`SECURITY_OPERATIONS.md`](SECURITY_OPERATIONS.md) | IAM, secrets, TLS, endpoint validation, and action gates. |
| MITRE ATT&CK/TTP | [`MITRE_TTP_OPERATIONS.md`](MITRE_TTP_OPERATIONS.md) | Bundled TTP ID data, refresh workflow, and validation expectations. |
| Recovery | [`RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`](RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md) | Failure behavior, retry semantics, ownership, and recovery duties. |
| Lambda image deployment | [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) | Lambda container image build and ECR deployment notes. |
| Testing | [`../testing/TESTING.md`](../testing/TESTING.md) | Unit, smoke, and optional integration validation commands. |
