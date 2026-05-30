# AWS / On-Prem Functional Parity Plan

## Status

Planning artifact only. Do not implement until this plan is reviewed and approved.

## Goal

Bring `s3_notable_pipeline` up to the currently implemented functional surface of
`llm_notable_analysis_onprem_systemd`, while preserving the existing AWS core
architecture:

```text
S3 incoming object -> Lambda -> Bedrock analysis -> S3 report output -> optional Splunk writeback
```

The AWS version should differ only where the deployment substrate differs. For
example, Bedrock Knowledge Bases stand in for on-prem Postgres/pgvector RAG, and
DynamoDB conditional writes stand in for on-prem file-backed side-effect
idempotency.

## Sources Used

This plan is based on the repository files, not memory:

- `AWS_NOTABLE_ANALYSIS_ENHANCEMENTS.md`
- `LLM_WORKFLOW_AND_HARNESS_POSITION.md`
- `s3_notable_pipeline/README.md`
- `s3_notable_pipeline/src/s3_notable_pipeline/lambda_handler.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/ttp_analyzer.py`
- `s3_notable_pipeline/deploy/aws/template-sam.yaml`
- `s3_notable_pipeline/deploy/aws/template-cfn.yaml`
- `s3_notable_pipeline/tests/test_lambda_handler.py`
- `llm_notable_analysis_onprem_systemd/docs/architecture/feature_enhancements_architecture.md`
- `llm_notable_analysis_onprem_systemd/docs/technical_specs/feature_enhancements_technical_spec.md`
- `llm_notable_analysis_onprem_systemd/docs/operations/README.md`
- `llm_notable_analysis_onprem_systemd/docs/operations/CAPABILITY_PROFILES.md`
- `llm_notable_analysis_onprem_systemd/docs/delivery_package/EXECUTIVE_ONPREM_WORKFLOW.md`
- `llm_notable_analysis_onprem_systemd/src/llm_notable_analysis_onprem_systemd/onprem_service/config.py`
- The on-prem implementation modules for SPL, Elastic, query-result enrichment,
  query-result interpretation, ServiceNow, HTML reports, and idempotency.

The planning rules and skills applied are:

- Requirements shaping and small diff planning.
- Project layout planning.
- Capability profile architecture.
- Cybersecurity workflow architecture.
- Deployment/runtime contract synchronization.
- AWS local testing with mocked clients or LocalStack.
- AWS Lambda least-privilege and consistency.
- Testing and documentation standards.

## Scope Contract

### In Scope

- Add AWS capability profiles matching on-prem operator semantics:
  `core`, `html_reports`, `rag`, `spl_readonly`, `elastic_readonly`,
  `ticket_draft`, and `action_gated`.
- Preserve existing `SPLUNK_SINK_MODE=s3|notable_rest` compatibility.
- Add Bedrock Knowledge Base retrieval for general SOC RAG context.
- Add separate Bedrock Knowledge Base retrieval for SPL query grounding.
- Add separate Bedrock Knowledge Base retrieval for Elasticsearch query grounding.
- Add SPL query generation as a second bounded Bedrock call.
- Add read-only Splunk investigation execution with `rest|mcp` executor choice.
- Add Elasticsearch Query DSL generation and bounded read-only execution.
- Add deterministic query-result enrichment before report rendering.
- Add optional query-result interpretation as an additional bounded Bedrock call.
- Add ServiceNow incident draft and approval-gated create behavior.
- Add side-effect idempotency for Splunk writeback and ServiceNow create using
  DynamoDB conditional writes and TTL.
- Add static HTML report output to S3 when enabled.
- Add AWS operations docs mirroring the on-prem operations doc shape.
- Add deterministic unit tests with mocked AWS, Splunk, Elastic, ServiceNow,
  MCP, and Bedrock clients.

### Out Of Scope

- Replacing the core S3/Lambda/Bedrock workflow.
- Moving the workflow to Step Functions.
- Adding the 90-day case archive, analyst portal, or Case Q&A assistant.
- Adding threat-intelligence adapters such as VirusTotal.
- Adding SOAR playbook invocation during investigation.
- Adding Langfuse/OpenTelemetry LLM tracing.
- Adding the golden evaluation harness or AI drift/integrity monitoring.
- Adding Athena or Security Lake investigation.
- Adding live AWS, Splunk, Elastic, ServiceNow, or MCP calls in unit tests.

## Parity Mapping

- On-prem `CAPABILITY_PROFILES` -> AWS `CAPABILITY_PROFILES` environment
  setting and SAM/CloudFormation parameters.
- On-prem local LLM/vLLM -> AWS Bedrock Converse using existing
  `BEDROCK_MODEL_ID`.
- On-prem general RAG Postgres/pgvector -> AWS Bedrock Knowledge Base retrieve.
- On-prem SPL query RAG Postgres table -> AWS separate Bedrock Knowledge Base id
  for SPL grounding.
- On-prem Elastic grounding table -> AWS separate Bedrock Knowledge Base id for
  Elasticsearch grounding.
- On-prem `INVESTIGATION_QUERY_EXECUTOR=rest|mcp` -> AWS same setting.
- On-prem file-backed idempotency markers -> AWS DynamoDB idempotency table.
- On-prem local markdown/HTML report files -> AWS S3 `reports/` markdown, JSON,
  and optional HTML objects.
- On-prem Splunk writeback -> Existing AWS `notable_rest` behavior, extended
  behind `action_gated` and idempotency.
- On-prem ServiceNow draft/create -> AWS ServiceNow REST with Secrets Manager
  token and payload-level approval metadata.

## Files To Create

This is the complete planned create list for the parity implementation. No other
files should be created unless the plan is updated and approved.

### Runtime And Support Code

- `s3_notable_pipeline/config.env.example`
- `s3_notable_pipeline/src/s3_notable_pipeline/aws_clients.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/config.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/bedrock_kb_retrieval.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/spl_query_generation.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/spl_query_grounding.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/splunk_investigation.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/elastic_query_generation.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/elasticsearch_query_grounding.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/elasticsearch_investigation.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/query_result_enrichment.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/query_result_interpretation.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/servicenow.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/html_generator.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/idempotency.py`

### Tests

- `s3_notable_pipeline/tests/test_aws_clients.py`
- `s3_notable_pipeline/tests/test_config.py`
- `s3_notable_pipeline/tests/test_bedrock_kb_retrieval.py`
- `s3_notable_pipeline/tests/test_spl_query_generation.py`
- `s3_notable_pipeline/tests/test_splunk_investigation.py`
- `s3_notable_pipeline/tests/test_elastic_query_generation.py`
- `s3_notable_pipeline/tests/test_elasticsearch_investigation.py`
- `s3_notable_pipeline/tests/test_query_result_enrichment.py`
- `s3_notable_pipeline/tests/test_query_result_interpretation.py`
- `s3_notable_pipeline/tests/test_servicenow.py`
- `s3_notable_pipeline/tests/test_html_generator.py`
- `s3_notable_pipeline/tests/test_idempotency.py`

### Operations, Testing, And Technical Docs

- `s3_notable_pipeline/docs/operations/README.md`
- `s3_notable_pipeline/docs/operations/CAPABILITY_PROFILES.md`
- `s3_notable_pipeline/docs/operations/LLM_INFERENCE_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/KNOWLEDGE_BASE_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/RAG_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/SPL_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/ELASTICSEARCH_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/SPLUNK_WRITEBACK_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/SERVICENOW_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/FILE_DROP_AND_RETENTION_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/SECURITY_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/MITRE_TTP_OPERATIONS.md`
- `s3_notable_pipeline/docs/operations/RECOVERY_BEHAVIOR_AND_RESPONSIBILITIES.md`
- `s3_notable_pipeline/docs/testing/TESTING.md`
- `s3_notable_pipeline/docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`

## Files Expected To Change

These existing files are expected to change during implementation:

- `s3_notable_pipeline/README.md`
- `s3_notable_pipeline/pyproject.toml`
- `s3_notable_pipeline/requirements.txt`
- `s3_notable_pipeline/src/s3_notable_pipeline/__init__.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/lambda_handler.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/ttp_analyzer.py`
- `s3_notable_pipeline/src/s3_notable_pipeline/markdown_generator.py`
- `s3_notable_pipeline/deploy/aws/template-sam.yaml`
- `s3_notable_pipeline/deploy/aws/template-cfn.yaml`
- `s3_notable_pipeline/scripts/setup-and-deploy.ps1`
- `s3_notable_pipeline/scripts/setup-and-deploy.sh`
- `s3_notable_pipeline/scripts/test-pipeline.ps1`
- `s3_notable_pipeline/docs/operations/DEPLOYMENT_IMAGE_STEPS.md`
- `s3_notable_pipeline/docs/delivery_package/EXECUTIVE_AWS_WORKFLOW.md`
- `s3_notable_pipeline/docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_OVERVIEW.md`
- `s3_notable_pipeline/docs/delivery_package/AIOPTIMIZED_SOC_ANALYSIS_AWS_READINESS_ASSESSMENT.md`
- `s3_notable_pipeline/docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.md`
- `s3_notable_pipeline/docs/delivery_package/end_to_end_diagrams/END_TO_END_DIAGRAMS.fig01-full-story.mmd`
- `s3_notable_pipeline/docs/security/ATTACK_LLM_ANALYSIS.md`
- `s3_notable_pipeline/tests/test_lambda_handler.py`

Generated diagram exports may change only if the diagram source is updated and
the export step is run:

- `s3_notable_pipeline/docs/delivery_package/end_to_end_diagrams/*.svg`
- `s3_notable_pipeline/docs/delivery_package/end_to_end_diagrams/*.png`

## Dependency Posture

No new third-party Python dependency is planned by default.

- AWS SDK access should use Lambda-provided `boto3` at runtime.
- Unit tests should mock AWS clients and must not require AWS credentials.
- Existing `requests` dependency remains sufficient for Splunk REST,
  Elasticsearch REST, ServiceNow REST, and MCP-over-HTTP if that is the selected
  runtime MCP transport.
- If a later MCP client implementation requires a new dependency, stop and
  request approval before adding it.

## Runtime Contract Additions

The exact parameter names will be locked in
`docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md` before coding each
slice. The planned env/SAM contract includes:

- `CAPABILITY_PROFILES`
- `HTML_REPORT_ENABLED`
- `RAG_ENABLED`
- `RAG_BEDROCK_KB_ID`
- `RAG_MAX_SNIPPETS`
- `RAG_CONTEXT_BUDGET_CHARS`
- `RAG_FAILURE_MODE`
- `SPL_QUERY_GENERATION_ENABLED`
- `SPL_QUERY_RAG_ENABLED`
- `SPL_QUERY_RAG_BEDROCK_KB_ID`
- `SPL_QUERY_RAG_MAX_SNIPPETS`
- `SPL_QUERY_RAG_CONTEXT_BUDGET_CHARS`
- `SPL_QUERY_RAG_FAILURE_MODE`
- `INVESTIGATION_QUERY_EXECUTION_ENABLED`
- `INVESTIGATION_QUERY_BACKEND`
- `INVESTIGATION_QUERY_EXECUTOR`
- `INVESTIGATION_MAX_QUERIES_PER_ALERT`
- `INVESTIGATION_MAX_CONCURRENT_QUERIES`
- `QUERY_RESULT_INTERPRETATION_ENABLED`
- `QUERY_RESULT_INTERPRETATION_CONTEXT_BUDGET_CHARS`
- `QUERY_RESULT_INTERPRETATION_MAX_SAMPLE_ROWS`
- `QUERY_RESULT_INTERPRETATION_MAX_TOKENS`
- `SPLUNK_SEARCH_ENDPOINT_PATH`
- `SPLUNK_SEARCH_ALLOWED_INDEXES`
- `SPLUNK_SEARCH_ALLOWED_COMMANDS`
- `SPLUNK_SEARCH_DENIED_COMMANDS`
- `SPLUNK_SEARCH_MAX_TIME_RANGE`
- `SPLUNK_SEARCH_MAX_ROWS`
- `SPLUNK_SEARCH_TIMEOUT_SECONDS`
- `SPLUNK_MCP_ENDPOINT`
- `SPLUNK_MCP_AUTH_SECRET_ARN`
- `SPLUNK_MCP_AUTH_SECRET_FIELD`
- `SPLUNK_MCP_HTTP_TIMEOUT_SECONDS`
- `SPLUNK_MCP_TOOL_NAME`
- `ELASTIC_QUERY_GENERATION_ENABLED`
- `ELASTICSEARCH_BASE_URL`
- `ELASTICSEARCH_API_KEY_SECRET_ARN`
- `ELASTICSEARCH_INDEX_ALLOWLIST`
- `ELASTICSEARCH_ALLOW_WILDCARD_INDEXES`
- `ELASTICSEARCH_TIMESTAMP_FIELD`
- `ELASTICSEARCH_ALLOWED_FIELDS`
- `ELASTICSEARCH_GROUNDING_ENABLED`
- `ELASTICSEARCH_GROUNDING_BEDROCK_KB_ID`
- `ELASTICSEARCH_GROUNDING_MAX_SNIPPETS`
- `ELASTICSEARCH_GROUNDING_CONTEXT_BUDGET_CHARS`
- `ELASTICSEARCH_GROUNDING_FAILURE_MODE`
- `ELASTICSEARCH_MAX_TIME_RANGE`
- `ELASTICSEARCH_MAX_ROWS`
- `ELASTICSEARCH_TIMEOUT_SECONDS`
- `SERVICENOW_DRAFT_ENABLED`
- `SERVICENOW_CREATE_ENABLED`
- `SERVICENOW_CREATE_REQUIRES_APPROVAL`
- `SERVICENOW_BASE_URL`
- `SERVICENOW_CREATE_PATH`
- `SERVICENOW_API_TOKEN_SECRET_ARN`
- `SERVICENOW_ASSIGNMENT_GROUP`
- `SERVICENOW_TIMEOUT_SECONDS`
- `SIDE_EFFECT_IDEMPOTENCY_ENABLED`
- `SIDE_EFFECT_IDEMPOTENCY_TABLE`
- `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS`

Planned SAM/CloudFormation deployment parameters also include:

- `LambdaTimeoutSeconds`
- `LambdaMemorySize`
- `LambdaEphemeralStorageMb`
- Bedrock Knowledge Base id parameters for general RAG, SPL grounding, and
  Elastic grounding.
- Secret ARN parameters for Splunk writeback, Splunk MCP, Elasticsearch, and
  ServiceNow.
- `SideEffectIdempotencyTableName` or equivalent table-name parameter.

## Planned Diff Sequence

### Diff 1: Config, AWS Clients, And Docs Skeleton

Objective:

- Add profile-aware config and centralized AWS client creation.
- Add the AWS operations doc skeleton and technical spec shell.
- Preserve current default runtime behavior.

Files:

- Create `config.env.example`, `aws_clients.py`, `config.py`.
- Create the operations index and technical spec.
- Update `lambda_handler.py`, SAM/CloudFormation templates, README, and tests.

Tests:

- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_config.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_aws_clients.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v`

Acceptance criteria:

- `CAPABILITY_PROFILES=core` preserves current S3 and `notable_rest` behavior.
- Unknown profiles fail fast.
- `spl_readonly` and `elastic_readonly` are mutually exclusive.
- Unit tests do not call real AWS.

### Diff 2: Bedrock KB RAG And HTML Reports

Objective:

- Add general SOC RAG retrieval through Bedrock Knowledge Bases.
- Add optional static HTML report output to S3.

Files:

- Create `bedrock_kb_retrieval.py` and `html_generator.py`.
- Update `ttp_analyzer.py`, `lambda_handler.py`, `markdown_generator.py`,
  templates, README, RAG/KB/LLM/docs, and tests.

Tests:

- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_bedrock_kb_retrieval.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_html_generator.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v`

Acceptance criteria:

- RAG context is advisory and separated from direct alert evidence.
- Bedrock KB retrieval failure follows configured failure mode.
- HTML output writes `reports/<stem>.html` only when enabled.

### Diff 3: SPL Generation, Grounding, And Splunk Investigation

Objective:

- Add SPL generation as a second bounded Bedrock call.
- Add SPL-specific Bedrock KB grounding.
- Add bounded read-only Splunk execution through REST or MCP.

Files:

- Create `spl_query_generation.py`, `spl_query_grounding.py`, and
  `splunk_investigation.py`.
- Update `ttp_analyzer.py`, `lambda_handler.py`, `markdown_generator.py`,
  templates, SPL/Splunk/security/docs, and tests.

Tests:

- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_spl_query_generation.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_splunk_investigation.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v`

Acceptance criteria:

- SPL fields are absent by default.
- Generated SPL must be tied to the six hypotheses.
- Policy denial prevents execution.
- REST and MCP paths use the same normalized query-result shape.
- MCP has no Cursor dependency; it is just a configured runtime integration.

### Diff 4: Query-Result Enrichment And Interpretation

Objective:

- Add deterministic query-result report enrichment.
- Add optional query-result interpretation as a separate bounded Bedrock call.

Files:

- Create `query_result_enrichment.py` and `query_result_interpretation.py`.
- Update `ttp_analyzer.py`, `lambda_handler.py`, `markdown_generator.py`,
  operations docs, technical spec, and tests.

Tests:

- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_query_result_enrichment.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_query_result_interpretation.py" -v`

Acceptance criteria:

- Deterministic query results render before interpretation.
- Interpretation never mutates existing confidence, TTP scores, query status,
  result counts, or source refs.
- Malformed interpretation output fails soft and keeps deterministic results.

### Diff 5: ServiceNow And Idempotency

Objective:

- Add ServiceNow draft and approval-gated create.
- Add DynamoDB idempotency for external side effects.
- Bring Splunk writeback under the same action-gated/idempotency posture while
  preserving existing `notable_rest` compatibility.

Files:

- Create `servicenow.py` and `idempotency.py`.
- Update `lambda_handler.py`, templates, docs, and tests.

Tests:

- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_servicenow.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_idempotency.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v`

Acceptance criteria:

- Draft creation has no network side effect.
- Create requires approval metadata when enabled.
- DynamoDB conditional writes prevent duplicate Splunk writeback and ServiceNow
  create side effects.
- Secrets are read from Secrets Manager and never logged.

### Diff 6: Elasticsearch Read-Only Parity And Final Docs

Objective:

- Add Elastic query generation, Bedrock KB grounding, and bounded `_search`
  execution.
- Finish AWS operations docs, testing docs, delivery docs, and diagrams.

Files:

- Create `elastic_query_generation.py`, `elasticsearch_query_grounding.py`, and
  `elasticsearch_investigation.py`.
- Update `lambda_handler.py`, `ttp_analyzer.py`, `markdown_generator.py`,
  templates, docs, diagrams, and tests.

Tests:

- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_elastic_query_generation.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_elasticsearch_investigation.py" -v`
- `python -m unittest discover -s s3_notable_pipeline/tests -p "test_*.py" -v`

Acceptance criteria:

- `elastic_readonly` and `spl_readonly` remain mutually exclusive.
- Elasticsearch base URL must be HTTPS when execution is enabled.
- Query DSL uses allowlisted indexes and fields only.
- AWS operations docs cover all new env vars, IAM permissions, secrets,
  lifecycle behavior, validation commands, and rollout order.

## Testing Strategy

- Unit tests use mocked AWS clients and fake HTTP clients.
- No unit test may require real AWS credentials, live Bedrock, live Splunk, live
  ServiceNow, live Elasticsearch, or a live MCP endpoint.
- Local AWS integration tests are optional and must use LocalStack if added later.
- Real AWS validation remains an explicit dev/staging/prod step, not a default
  test path.

Planned primary command after each slice:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_*.py" -v
```

## Documentation Parity Requirements

Every new runtime contract must be updated in the same diff across:

- Code defaults and validation.
- SAM and CloudFormation parameters/env vars.
- `config.env.example`.
- AWS operations docs.
- README or delivery docs when operator-facing.
- Tests.

The AWS operations docs should follow the same guide shape as on-prem:

- What this controls.
- Recommended starting posture.
- Customer decisions.
- Config quick reference.
- Validation and rollout.
- Related docs.

## Security And Governance Requirements

- Default-off for RAG, SPL execution, Elastic execution, ServiceNow, HTML, and
  external write/action behavior.
- Read-only query execution must be policy-gated before any external call.
- Consequential writes require explicit enablement and approval where applicable.
- Bedrock KB content is advisory context, not direct alert evidence.
- Secrets must use Secrets Manager or equivalent secure injection.
- IAM must be narrowed to configured resources: S3 prefixes, Bedrock model/KB,
  Secrets Manager ARNs, and DynamoDB idempotency table.
- Do not log tokens, auth headers, full prompts, or bulk sensitive payloads.

## AWS Infrastructure And Second-Order Effects To Account For

Each implementation slice must account for the AWS resources and operational
effects it introduces. This is required parity work, not optional cleanup.

### Lambda Container And Runtime Resources

- Add SAM/CloudFormation parameters for Lambda `Timeout`, `MemorySize`, and
  ephemeral storage instead of hardcoding these values.
- Preserve current conservative defaults for `core`: `LambdaTimeoutSeconds=360`,
  `LambdaMemorySize=512`, and `LambdaEphemeralStorageMb=512`.
- Document recommended starting values for parity profiles that add multiple
  model calls or external queries: `LambdaTimeoutSeconds=900`,
  `LambdaMemorySize=1024`, and `LambdaEphemeralStorageMb=512`. Increase memory
  only after CloudWatch duration/memory evidence shows it is needed.
- Confirm the container image includes every new source module and package-data
  file required at runtime.
- Re-run the image build/deploy documentation whenever `pyproject.toml`,
  `requirements.txt`, package data, or handler imports change.
- Keep dependency growth controlled. No new third-party dependency is planned by
  default; if one becomes necessary, update image build docs and request approval.
- Validate Lambda timeout budget against downstream timeouts:
  Bedrock base call, Bedrock KB retrieval, SPL/Elastic query execution,
  ServiceNow create, Splunk writeback, and optional interpretation.

### IAM And AWS Service Permissions

- Bedrock model invocation permissions must still match `BEDROCK_MODEL_ID`.
- Bedrock Knowledge Base retrieval permissions must be scoped to configured KB
  ARNs/ids for general RAG, SPL grounding, and Elastic grounding.
- Secrets Manager permissions must be scoped to only the Splunk, MCP,
  Elasticsearch, and ServiceNow secret ARNs actually configured.
- DynamoDB permissions for idempotency must be limited to the idempotency table
  and only the required actions, such as conditional `PutItem`, `GetItem`, and
  TTL-compatible attributes.
- S3 permissions must remain limited to input read and output report prefixes;
  adding HTML or JSON artifacts must not require broad bucket access.
- CloudWatch Logs permissions remain limited to the Lambda log group.

### Network And Connectivity

- Splunk REST, Splunk MCP, Elasticsearch, and ServiceNow endpoints may require
  VPC attachment, subnet/security group configuration, NAT, PrivateLink, or
  customer network routing. The plan must document these as deployment decisions,
  not code assumptions.
- Bedrock and Bedrock Knowledge Bases must be reachable from the chosen Lambda
  networking mode. If the Lambda is VPC-attached, account for NAT or VPC endpoint
  requirements where applicable.
- TLS verification must remain on by default for Splunk, Elastic, MCP-over-HTTPS,
  and ServiceNow. Any custom CA behavior must be explicit and documented.

### Eventing, Retries, And Idempotency

- S3 event delivery can retry or duplicate events. Existing one-object/one-run
  behavior must remain, while external side effects use DynamoDB idempotency when
  enabled.
- Idempotency keys must be deterministic and scoped by side-effect type, such as
  Splunk writeback finding id and ServiceNow correlation id.
- Partial failures must be visible: report writes, Splunk writeback, ServiceNow
  create, query execution, and idempotency denial should each have clear status
  metadata.
- DynamoDB TTL must match `SIDE_EFFECT_IDEMPOTENCY_RETENTION_DAYS` and be
  documented as best-effort expiration, not immediate deletion.

### Quotas, Cost, And Performance

- Bedrock calls can increase from one call to up to three model calls per
  notable: base analysis, optional SPL/Elastic generation, and optional
  query-result interpretation.
- Bedrock Knowledge Base retrieval adds additional API calls for general RAG,
  SPL grounding, and Elastic grounding.
- Splunk and Elasticsearch execution can add up to
  `INVESTIGATION_MAX_QUERIES_PER_ALERT` external searches per notable, bounded by
  `INVESTIGATION_MAX_CONCURRENT_QUERIES`.
- CloudWatch log volume, S3 output volume, DynamoDB writes, Bedrock usage, and
  downstream Splunk/Elastic load should be called out in operations docs.
- SAM/CloudFormation parameters should expose only needed tuning knobs; defaults
  must keep optional higher-cost features off.

### Deployment And Validation Artifacts

- Both `template-sam.yaml` and `template-cfn.yaml` must be updated together for
  new env vars, IAM, DynamoDB, Secrets Manager references, and Bedrock KB
  permissions.
- Deployment scripts must pass or prompt for any new required parameters.
- `scripts/test-pipeline.ps1` should remain a `core` smoke test by default and
  add documented optional checks for enabled profiles only when safe.
- Operations docs must state what resources must exist before enabling each
  profile: Bedrock KBs, Secrets Manager secrets, DynamoDB table, VPC routing,
  Splunk/MCP/Elastic/ServiceNow endpoints, and S3 lifecycle expectations.

## Implementation Decisions To Follow

These decisions are locked for the parity implementation unless this plan is
updated and re-approved.

- Create `s3_notable_pipeline/config.env.example` as the AWS runtime contract
  companion to SAM/CloudFormation parameters.
- Create an AWS-specific technical spec in
  `docs/technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`.
- Add a DynamoDB table to the AWS templates for idempotency.
- Implement MCP as a configured runtime HTTP/client integration with no Cursor
  dependency and no new Python dependency.
- Keep no new Python dependencies unless a later implementation step explicitly
  proves one is required and gets approval.

## Resolved Planning Decisions

- Maintain both `deploy/aws/template-sam.yaml` and
  `deploy/aws/template-cfn.yaml` as first-class deployment templates during the
  parity work.
- Keep `INVESTIGATION_QUERY_EXECUTOR=mcp` as an AWS parity option. Implement the
  AWS MCP path as MCP-over-HTTPS using the existing `requests` dependency:
  `POST {SPLUNK_MCP_ENDPOINT}` with a JSON body equivalent to the on-prem
  `run_search(payload: dict) -> dict` payload:
  `tool_name`, `query`, `query_dialect`, `time_range`, `max_rows`, and
  `timeout_seconds`. Require `SPLUNK_MCP_ENDPOINT` to be HTTPS with no URL
  userinfo when the MCP executor is enabled. Use `SPLUNK_MCP_AUTH_SECRET_ARN`
  plus `SPLUNK_MCP_AUTH_SECRET_FIELD` (default `token`) as an optional bearer
  token source; if omitted, the endpoint must be protected by deployment network
  controls. Bound the HTTP request with `SPLUNK_MCP_HTTP_TIMEOUT_SECONDS`
  (default `SPLUNK_SEARCH_TIMEOUT_SECONDS + 5`, capped at the Lambda remaining
  time). Operations docs must state that AWS deployments selecting `mcp` must
  provide a reachable MCP bridge/client endpoint; no Cursor MCP dependency is
  involved.
- Use SAM/CloudFormation parameters as the official configuration path for
  Bedrock Knowledge Base ids. The templates populate Lambda environment
  variables from those parameters. The runtime code reads environment variables
  because that is how Lambda receives deployed configuration, but operations docs
  should direct operators to set KB ids through deployment parameters, not manual
  Lambda console edits.
- Match the on-prem writeback posture: `action_gated` is the preferred
  operator-facing profile for external write/action behavior and enables Splunk
  notable writeback plus side-effect idempotency. Preserve existing
  `SPLUNK_SINK_MODE=notable_rest` compatibility as the AWS legacy/lab-style
  direct enablement path, but document that new parity deployments should use
  `CAPABILITY_PROFILES=core,action_gated` and keep idempotency enabled.
- Add Lambda resource tuning as deployment parameters. Keep existing defaults for
  backward-compatible core deployments, and document `900` seconds / `1024` MB as
  the starting point for deployments enabling RAG plus read-only investigation
  and optional interpretation.

## Things This Plan Intentionally Does Not Change

- The existing S3 `incoming/` trigger.
- The existing Lambda as the primary orchestrator.
- The existing Bedrock base analysis call.
- Existing S3 report output.
- Existing `SPLUNK_SINK_MODE=s3|notable_rest` behavior.
- The lack of case archive, portal, and Case Q&A in the current AWS product.

## Open Questions

None for the current planning block.

