# Azure operations documentation

| Area | Runbook |
| --- | --- |
| Customer configuration | [`deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md`](deployment/AZURE_GOVERNMENT_CUSTOMER_CONFIGURATION.md) |
| Build/deploy/rollback | [`deployment/DEPLOYMENT_IMAGE_STEPS.md`](deployment/DEPLOYMENT_IMAGE_STEPS.md) |
| Testing and Azure Government validation | [`testing/AZURE_GOVERNMENT_TESTING.md`](testing/AZURE_GOVERNMENT_TESTING.md) |
| Golden evaluation | [`testing/GOLDEN_EVALUATION.md`](testing/GOLDEN_EVALUATION.md) |
| Azure OpenAI inference | [`llm/LLM_INFERENCE_OPERATIONS.md`](llm/LLM_INFERENCE_OPERATIONS.md) |
| Azure AI Search | [`rag/KNOWLEDGE_BASE_OPERATIONS.md`](rag/KNOWLEDGE_BASE_OPERATIONS.md) |
| RAG and knowledge ingestion | [`rag/AZURE_AI_SEARCH_RAG_INGESTION.md`](rag/AZURE_AI_SEARCH_RAG_INGESTION.md) |
| Capability profiles | [`platform/CAPABILITY_PROFILES.md`](platform/CAPABILITY_PROFILES.md) |
| Security | [`security/AZURE_GOVERNMENT_SECURITY.md`](security/AZURE_GOVERNMENT_SECURITY.md) |
| MITRE ATT&CK | [`security/MITRE_ATTACK_OPERATIONS.md`](security/MITRE_ATTACK_OPERATIONS.md) |
| Retention and recovery | [`retention/AZURE_RETENTION_AND_RECOVERY.md`](retention/AZURE_RETENTION_AND_RECOVERY.md) |
| Analyst portal | [`analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](analyst_portal/ANALYST_PORTAL_OPERATIONS.md) |
| Portal deployment gate | [`ANALYST_PORTAL_DEPLOYMENT.md`](ANALYST_PORTAL_DEPLOYMENT.md) |
| Monitoring, poison replay, escalation | [`AZURE_MONITORING_AND_RECOVERY.md`](AZURE_MONITORING_AND_RECOVERY.md) |
| Storage, Functions, and Cosmos resilience | [`AZURE_RESILIENCE_PROFILE.md`](AZURE_RESILIENCE_PROFILE.md) |
| Account-free local parity lab | [`LOCAL_AZURE_PARITY.md`](LOCAL_AZURE_PARITY.md) |
| ServiceNow disposition sync | [`integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md`](integrations/SERVICENOW_DISPOSITION_SYNC_OPERATIONS.md) |
| SIEM/SOAR private intake | [`integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md`](integrations/SIEM_SOAR_PRIVATE_INTAKE_OPERATIONS.md) |
| Splunk, Elasticsearch, and writeback | [`investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md`](investigation/SPLUNK_ELASTICSEARCH_WRITEBACK.md) |
| ServiceNow action boundaries | [`integrations/SERVICENOW_WRITEBACK_OPERATIONS.md`](integrations/SERVICENOW_WRITEBACK_OPERATIONS.md) |

The three poison paths are independent and never auto-replayed. Operators must
correct the cause, check for an already durable outcome, and replay one message
through its normal idempotent path.
