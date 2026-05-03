# TODO: AWS notable pipeline — feature parity with on-prem enhancements

This checklist tracks **optional capabilities that exist (or are specified) for `llm_notable_analysis_onprem_systemd/`** but are **not present today in `s3_notable_pipeline/`** (S3 → Lambda → Bedrock → sinks).

**Normative on-prem contract:** [`llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md`](llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md)  
**Architecture companion:** [`llm_notable_analysis_onprem_systemd/docs/architecture/feature_enhancements_architecture.md`](llm_notable_analysis_onprem_systemd/docs/architecture/feature_enhancements_architecture.md)

**Current AWS baseline (for contrast):** ingest from S3, Bedrock analysis with validation/repair, ATT&CK ID filtering, markdown report, sink to output S3 and/or Splunk **notable comment** REST (`notable_rest` mode). No separate investigation queries, no ServiceNow, no RAG/KB grounding in the Lambda path.

---

## 1. SPL query generation (second bounded LLM call)

- [ ] Port or reimplement the **SPL-only second call** pattern (`SPL_QUERY_GENERATION_ENABLED`): hypotheses → structured SPL query fields, contract validation, merge-by-position, repair-once behavior.
- [ ] Align output schema and validators with on-prem `spl_query_generation.py` behavior (and tests as reference: `llm_notable_analysis_onprem_systemd/tests/onprem_service/test_spl_query_generation.py`).
- [ ] Decide Bedrock structured output shape for AWS (tool use vs prompt-JSON) and mirror `LLM_STRUCTURED_OUTPUT_MODE`-style controls if needed.

## 2. Read-only Splunk investigation (execute generated SPL)

- [ ] Add **read-only** Splunk search execution (REST oneshot path) with the same **policy gates** as on-prem: allowed indexes/commands, denied commands, time bounds, row caps, timeouts (see spec §8).
- [ ] Wire **after** SPL generation: validate → execute → capture normalized results (no treating raw search rows as “alert evidence” without labeling).
- [ ] Network path: Lambda in VPC to Splunk management/API host; secrets via Secrets Manager/Parameter Store; avoid embedding tokens in env defaults.

## 3. Splunk MCP executor (optional parity)

- [ ] On-prem supports `INVESTIGATION_QUERY_EXECUTOR=rest|mcp`. If MCP is required in AWS, define **how** Lambda reaches MCP (private integration, proxy, or defer and document “REST-only on AWS v1”).

## 4. Query-result enrichment + markdown

- [ ] Port deterministic **`query_result_section`** enrichment (attempted / denied / skipped / failed states, compact samples).
- [ ] Extend AWS markdown generator with a **Query Results** section when enrichment is present (`query_result_enrichment.py` / markdown tests as reference).

## 5. ServiceNow incident draft and approval-gated create

- [ ] **Draft** incident payload from analysis (no network side effect when draft-only).
- [ ] **Create** incident only with explicit approval metadata (spec §12); normalize responses; never log tokens.
- [ ] Decide how approval is supplied for AWS (e.g. field inside uploaded notable JSON vs separate control plane).
- [ ] IAM/network: outbound HTTPS to ServiceNow; secrets handling; timeouts aligned with Lambda remaining time.

## 6. RAG / KB grounding (SOPs, data dictionary, index docs)

- [ ] On-prem: SQLite FTS + FAISS + local embedding model (`RAG_*` in `config.env.example`). **Lambda is not a drop-in host for that stack** — pick an AWS-shaped approach (for example Bedrock Knowledge Bases, OpenSearch, Aurora/pgvector, or a dedicated small retrieval service) and treat this as an **architecture milestone**, not a straight file copy.
- [ ] If AWS RAG lands, keep the same **trust boundary**: retrieved text is advisory context, not notable evidence unless reflected in the alert payload.

## 7. Operational / product siblings (optional)

- [ ] **Freeform / alternate entrypoints:** on-prem has separate modules/services (e.g. freeform analyzer). Decide whether AWS needs an API Gateway + Lambda variant or stays batch-only.
- [ ] **Retention:** on-prem uses systemd timers; AWS typically uses **S3 lifecycle**, optional EventBridge cleanup, or downstream ops — document equivalence rather than porting `retention.py` literally.

## 8. Cross-cutting requirements (when implementing any item above)

- [ ] **Default-off flags** for risky capabilities; fail-closed validation; same orchestration order idea as spec §11 (analysis → optional SPL gen → optional execute → enrich → markdown → optional SNOW).
- [ ] **Deterministic tests** with fakes (no live Splunk/ServiceNow/Bedrock in unit tests); extend `s3_notable_pipeline/tests/`.
- [ ] **Contract sync:** SAM/template parameters, README, and operator docs updated whenever new secrets, VPC wiring, or payload fields are introduced ([`s3_notable_pipeline/README.md`](s3_notable_pipeline/README.md), [`docs/operations/DEPLOYMENT_IMAGE_STEPS.md`](s3_notable_pipeline/docs/operations/DEPLOYMENT_IMAGE_STEPS.md)).

---

## Suggested sequencing

1. SPL query generation only (no execution) — smallest additive Bedrock change, lowest blast radius.  
2. REST investigation + enrichment + markdown — highest analyst value; requires VPC + Splunk policy testing.  
3. ServiceNow draft/create — approval and CMDB/process alignment with stakeholders.  
4. RAG — depends on chosen AWS retrieval architecture.  
5. MCP executor — only if REST-only is insufficient.

_Last updated: aligns with on-prem feature-enhancement spec as a planning backlog; not a commitment order._
