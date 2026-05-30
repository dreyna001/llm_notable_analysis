# SPL Operations

## What This Controls

This guide covers optional SPL generation, SPL-specific Bedrock Knowledge Base
grounding, and read-only Splunk investigation query execution for AWS
deployments.

## Recommended Starting Posture

Keep SPL generation and query execution disabled for the first `core` rollout.
Enable them only after the customer has approved the allowed indexes, commands,
query time range, row cap, network path to Splunk or MCP, and Knowledge Base
content used for SPL grounding.

For parity deployments, start with:

- `CAPABILITY_PROFILES=core,spl_readonly`
- `INVESTIGATION_QUERY_EXECUTOR=rest` unless the customer has a managed MCP
  bridge endpoint.
- `LambdaTimeoutSeconds=900` and `LambdaMemorySize=1024` when RAG plus
  read-only investigation are both enabled.

## Customer Decisions

- Which Splunk indexes are safe for read-only investigation queries?
- Which SPL commands are allowed and which commands are denied?
- Should AWS call Splunk REST directly, or call a customer-managed MCP bridge
  over HTTPS?
- Which Bedrock Knowledge Base contains customer-approved SPL index,
  sourcetype, macro, and data model guidance?
- What network path is required from Lambda to Splunk or the MCP bridge?

## Config Quick Reference

- `CAPABILITY_PROFILES=core,spl_readonly`
- `SPL_QUERY_RAG_BEDROCK_KB_ID`
- `INVESTIGATION_QUERY_EXECUTOR=rest|mcp`
- `SPLUNK_BASE_URL`
- `SPLUNK_API_TOKEN_SECRET_ARN`
- `SPLUNK_SEARCH_ALLOWED_INDEXES`
- `SPLUNK_SEARCH_ALLOWED_COMMANDS`
- `SPLUNK_SEARCH_DENIED_COMMANDS`
- `SPLUNK_SEARCH_ALLOWED_FIELDS`
- `SPLUNK_SEARCH_MAX_TIME_RANGE`
- `SPLUNK_SEARCH_MAX_ROWS`
- `SPLUNK_SEARCH_TIMEOUT_SECONDS`
- `SPLUNK_MCP_ENDPOINT`
- `SPLUNK_MCP_AUTH_SECRET_ARN`

SAM and CloudFormation parameters are the official deployment path. Lambda
environment variables are the runtime representation of those parameters.

## Validation And Rollout

1. Deploy with `CAPABILITY_PROFILES=core` and confirm the base S3 report path.
2. Create or select the SPL grounding Knowledge Base and confirm its snippets
   contain only approved operational query guidance.
3. Enable `core,spl_readonly` in a non-production stack with narrow indexes and
   row limits.
4. Verify generated SPL appears in JSON and markdown reports.
5. Confirm denied queries, including subsearch or macro syntax, do not make a
   network call.
6. Confirm REST or MCP results are normalized under `investigation_query_results`.
7. Confirm returned sample rows omit `_raw` and retain only approved fields when
   `SPLUNK_SEARCH_ALLOWED_FIELDS` is set.

Unit test commands:

```bash
python -m unittest discover -s s3_notable_pipeline/tests -p "test_spl_query_generation.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_splunk_investigation.py" -v
python -m unittest discover -s s3_notable_pipeline/tests -p "test_lambda_handler.py" -v
```

## Related Docs

- `../technical_specs/AWS_ONPREM_PARITY_TECHNICAL_SPEC.md`
- `KNOWLEDGE_BASE_OPERATIONS.md`
- `RAG_OPERATIONS.md`
- `SECURITY_OPERATIONS.md`
