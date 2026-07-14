# Azure operations documentation

| Area | Runbook |
| --- | --- |
| Build/deploy/rollback | [`deployment/DEPLOYMENT_IMAGE_STEPS.md`](deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Foundry Claude and Azure OpenAI | [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) |
| Azure AI Search | [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| Analyst portal | [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Portal deployment gate | [`ANALYST_PORTAL_DEPLOYMENT.md`](ANALYST_PORTAL_DEPLOYMENT.md) |
| Monitoring, poison replay, escalation | [`AZURE_MONITORING_AND_RECOVERY.md`](AZURE_MONITORING_AND_RECOVERY.md) |
| Storage, Functions, and Cosmos resilience | [`AZURE_RESILIENCE_PROFILE.md`](AZURE_RESILIENCE_PROFILE.md) |
| Account-free local parity lab | [`LOCAL_AZURE_PARITY.md`](LOCAL_AZURE_PARITY.md) |
| ServiceNow disposition sync | [`integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) |
| SIEM/SOAR private intake | [`integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md`](integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md) |

The three poison paths are independent and never auto-replayed. Operators must
correct the cause, check for an already durable outcome, and replay one message
through its normal idempotent path.
