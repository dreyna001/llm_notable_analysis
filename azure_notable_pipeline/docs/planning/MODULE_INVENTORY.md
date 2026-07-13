# AWS-to-Azure Module Inventory

This inventory classifies every top-level source module in the AWS package at
the Phase 0 baseline. “Copied” means behavior is present now. “Deferred” means
the Azure owner is named but the AWS cloud implementation was deliberately not
copied.

| AWS source | Class | Azure owner | Capability | Phase 0 disposition | Test owner |
| --- | --- | --- | --- | --- | --- |
| `__init__.py` | Tier A | `__init__.py` | package | Copied; package description updated | import/scaffold |
| `aws_clients.py` | AWS-only/replaced | `azure_clients.py` | all cloud clients | Omitted; native factory shell created | `test_azure_scaffold.py`, Phase 1/2 client tests |
| `bedrock_kb_retrieval.py` | AWS-only/replaced | `azure_search_retrieval.py` | RAG/grounding | Omitted; native bounded Search boundary implemented | `test_azure_search_retrieval.py` |
| `case_archive.py` | Tier C | `case_archive.py` + `blob_store.py` + `cosmos_store.py` | analyst portal | Ported with deterministic envelope/index identity, retention, collision/replay behavior, and native conditional create | `test_case_archive.py` |
| `case_archive_notices.py` | Tier A | same filename | analyst portal | Copied | `test_case_archive_notices.py` |
| `case_chat.py` | Tier C | same filename + `azure_openai_gateway.py` | analyst portal | Deferred | Phase 3 chat tests |
| `case_chat_history.py` | Tier C | same filename + `cosmos_store.py` | analyst portal | Deferred | Phase 2/3 history tests |
| `case_chunk_retrieval.py` | Tier B | same filename + Azure gateways | analyst portal | Ported with bounded chunk source and Azure OpenAI embeddings | `test_case_chunk_retrieval.py` |
| `case_embed.py` | Tier C | same filename + Azure gateways | analyst portal | Ported with deterministic bounded chunk replacement, 1024-d Azure OpenAI vectors, and ETag-retried Cosmos status | `test_case_embed.py` |
| `case_index.py` | Tier C | same filename + `cosmos_store.py` | analyst portal | Deferred | Phase 2/3 index tests |
| `chat_context_usage.py` | Tier A | same filename | analyst portal | Copied | Phase 3 portable test (depends on `portal_chat.py`) |
| `config.py` | Tier B | same filename | all profiles | Azure runtime contract ported | `test_config.py` |
| `disposition_sync_handler.py` | Tier C | same filename + timer wrapper | disposition sync | Deferred | Phase 4 native timer tests |
| `elastic_query_generation.py` | Tier A | same filename | elastic read-only | Copied | `test_elastic_query_generation.py` |
| `elasticsearch_investigation.py` | Tier A | same filename | elastic read-only | Copied | `test_elasticsearch_investigation.py` |
| `elasticsearch_query_grounding.py` | Tier B | same filename + `azure_search_retrieval.py` | elastic grounding | Ported to stable native Search results | `test_query_grounding_retrieval.py` |
| `embed_handler.py` | Tier C | same filename + queue wrapper | analyst portal | Strict native dispatcher invokes Blob/OpenAI/Cosmos workflow; failures propagate for Queue retry/poison | `test_embed_handler.py`, `test_function_app_runtime.py` |
| `enterprise_attack_v17.1_ids.json` | Tier A asset | same filename | analyzer validation | Copied | Phase 1 analyzer tests |
| `html_generator.py` | Tier A | same filename | HTML reports | Copied | `test_html_generator.py` |
| `idempotency.py` | Tier C | same filename + `cosmos_store.py` | action gated | Disabled-path shell only; no database emulation | Phase 2 Cosmos tests |
| `lambda_handler.py` | AWS-only/replaced | `blob_handler.py` + `function_app.py` | core intake + optional analyzer profiles | Native queue/intake and AWS-ordered RAG/SPL/Elasticsearch orchestration implemented without AWS event/client shapes | Phase 1 queue/event tests + `test_optional_profile_orchestration.py` |
| `markdown_generator.py` | Tier A | same filename | core reports | Copied | `test_markdown_generator.py` |
| `portal_api_models.py` | Tier A | same filename | analyst portal API | Copied | Phase 3 API contract tests |
| `portal_chat.py` | Tier B | same filename + `azure_openai_gateway.py` | analyst portal | Deferred | Phase 3 chat tests |
| `portal_chat_kb.py` | Tier B | same filename + `azure_search_retrieval.py` | analyst portal | Advisory Search lanes ported; chat orchestration remains Phase 3 | `test_portal_chat_kb.py` |
| `portal_chat_kb_query.py` | Tier A | same filename | analyst portal | Copied | `test_portal_chat_kb_query.py` |
| `portal_handler.py` | Tier C | same filename + native HTTP wrappers | analyst portal | Deferred | Phase 3 native HTTP tests |
| `portal_jwt.py` | Tier A | same filename | portal authorization | Copied | `test_portal_jwt.py` |
| `query_result_enrichment.py` | Tier A | same filename | investigations | Copied | `test_query_result_enrichment.py` |
| `query_result_interpretation.py` | Tier A | same filename | investigations | Copied | `test_query_result_interpretation.py` |
| `runtime_security.py` | Tier B | same filename + `secret_provider.py` | external integrations | Ported to native secret boundary | config/integration tests |
| `servicenow.py` | Tier A | same filename | ticket draft/action | Copied unchanged | `test_servicenow.py` |
| `servicenow_disposition_sync.py` | Tier C | same filename + `cosmos_store.py` | disposition sync | Deferred | Phase 2/4 sync tests |
| `spl_query_generation.py` | Tier A | same filename | SPL read-only | Copied | `test_spl_query_generation.py` |
| `spl_query_grounding.py` | Tier B | same filename + `azure_search_retrieval.py` | SPL grounding | Ported to stable native Search results | `test_query_grounding_retrieval.py` |
| `splunk_investigation.py` | Tier A | same filename | SPL read-only | Copied | `test_splunk_investigation.py` |
| `ttp_analyzer.py` | Tier C | same filename + `azure_anthropic_gateway.py` | core analysis + optional query synthesis | Native forced-tool analysis and bounded text-only SPL/Elasticsearch generation/result interpretation implemented with copied deterministic validators | Phase 1 prompt/golden/native gateway tests + Phase 2 optional generation tests |
| `verdicts.py` | Tier A | same filename | report/API normalization | Copied | `test_verdicts.py` |

## AWS test disposition

| AWS test | Azure disposition | Owner |
| --- | --- | --- |
| `test_aws_clients.py` | Replaced by native factory tests | Phase 1/2 |
| `test_bedrock_kb_retrieval.py` | Replaced by Azure AI Search tests | Phase 2 |
| `test_case_archive.py` | Ported to Blob/Cosmos fakes with durable-schema and replay/collision assertions | Phase 2 |
| `test_case_archive_notices.py` | Copied | Phase 0 |
| `test_case_chat.py` | Port to Azure OpenAI gateway fake | Phase 3 |
| `test_case_chat_history.py` | Port to Cosmos store fake | Phase 2/3 |
| `test_case_chunk_retrieval.py` | Ported to application source and Azure OpenAI gateway fakes | Phase 2 |
| `test_case_embed.py` | Ported to Azure embeddings/Cosmos/Blob fakes | Phase 2 |
| `test_case_index.py` | Port to Cosmos native contract | Phase 2 |
| `test_chat_context_usage.py` | Copy when `portal_chat.py` lands | Phase 3 |
| `test_config.py` | Foundry/Sonnet runtime contract port | Phase 0 |
| `test_deploy_templates.py` | Replaced by Bicep tests | Phase 1–4 |
| `test_elastic_query_generation.py` | Copied | Phase 0 |
| `test_elasticsearch_investigation.py` | Copied | Phase 0 |
| `test_embed_handler.py` | Replaced by strict native queue dispatch/retry tests | Phase 2 |
| `test_golden_eval.py` | Reuse manifest/rubric after analyzer port | Phase 1 |
| `test_html_generator.py` | Copied | Phase 0 |
| `test_idempotency.py` | Replace database transport assertions with Cosmos outcomes | Phase 2 |
| `test_lambda_handler.py` | Replace with native polling Blob-trigger/queue/intake tests | Phase 1 |
| `test_markdown_generator.py` | Copied | Phase 0 |
| `test_portal_api_contract.py` | Reuse assertions after native handler lands | Phase 3 |
| `test_portal_chat.py` | Port to native gateway/search boundaries | Phase 3 |
| `test_portal_chat_kb_query.py` | Copied | Phase 0 |
| `test_portal_handler.py` | Replace transport assertions with native HTTP tests | Phase 3 |
| `test_portal_jwt.py` | Copied | Phase 0 |
| `test_portal_openapi_contract.py` | Copied; sync-script case deferred | Phase 0/3 |
| `test_query_result_enrichment.py` | Copied | Phase 0 |
| `test_query_result_interpretation.py` | Copied | Phase 0 |
| `test_servicenow.py` | Copied; disabled idempotency path uses Azure shell | Phase 0 |
| `test_servicenow_disposition_sync.py` | Port to Cosmos contract | Phase 2/4 |
| `test_spl_query_generation.py` | Copied | Phase 0 |
| `test_splunk_investigation.py` | Copied | Phase 0 |
| `test_ttp_analyzer_prompts.py` | Reuse prompt assertions after native analyzer port | Phase 1 |
| `test_verdicts.py` | Copied | Phase 0 |

Azure-only `test_config_contract.py` preserves the broader capability-profile,
validation, portal timeout, and no-AWS-alias assertions from the portable AWS
config suite.
