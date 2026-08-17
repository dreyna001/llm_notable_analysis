# GovCloud customer-default deployment

One-shot SAM preset for the on-prem **customer-default** bundle on GovCloud
AWS (`aws-us-gov`, `us-gov-east-1`):

- `CapabilityProfiles=core,rag,analyst_portal`
- General SOC RAG + Splunk dictionary grounding for portal chat
- Case archive, CaseIndex, read-only portal API, pinned-case Q&A
- **No** `spl_readonly` (no first-pass SPL generation or live Splunk queries)
- **No** closed-ticket RAG (planned in parity backlog P3–P7)

On-prem normative reference:
[`../../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md)

**Path B step 7** (SAM deploy):
[`../../../README.md`](../../../README.md#path-b-customer-default).

## Preset files (copy and fill)

| File | Purpose |
| --- | --- |
| [`../../../deploy/aws/presets/customer-default.env.example`](../../../deploy/aws/presets/customer-default.env.example) | Placeholder env file; source before `sam deploy --parameter-overrides` |
| [`../../../deploy/aws/presets/samconfig.customer-default.toml.example`](../../../deploy/aws/presets/samconfig.customer-default.toml.example) | Copy to project-root `samconfig.toml` for repeat deploys |

Complete Path B steps 1–6 before `sam deploy` (authoritative order:
[`../../../README.md`](../../../README.md#path-b-customer-default)):

| Step | Runbook |
| --- | --- |
| 1 (optional) | [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) |
| 2 | [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md) |
| 3 | [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) — Phase A |
| 4 | [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md) |
| 5 | [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) |
| 6 | [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) |

Fill `customer-default.env` from those runbooks (account ID, image digest, OpenSearch, VPC, Bedrock, JWT, optional CMK).
Indexes (`soc_knowledge`, `splunk_dictionary`, `case_chunks`) auto-create on first ingest or case embed.

## Why both profiles and explicit flags

`CapabilityProfiles` drives runtime behavior in the Lambda image. The SAM template
also uses explicit `*_Enabled` parameters to create queues, Lambdas, DynamoDB
tables, and API routes. For customer-default, set **both** to the same intent:

| SAM parameter | Customer-default value |
| --- | --- |
| `CapabilityProfiles` | `core,rag,analyst_portal` |
| `SplunkSinkMode` | `s3` |
| `HtmlReportEnabled` | `false` |
| `RagEnabled` | `true` |
| `RagIngestionEnabled` | `true` |
| `SplQueryRagEnabled` | `true` |
| `PortalEnabled` | `true` |
| `CaseArchiveEnabled` | `true` |
| `CaseQaEnabled` | `true` |

Do **not** add `spl_readonly`, `elastic_readonly`, `ticket_draft`, or
`action_gated` for this preset.

Full customer values checklist:
[`GOVCLOUD_CUSTOMER_CONFIGURATION.md`](GOVCLOUD_CUSTOMER_CONFIGURATION.md).

## Deploy (fast path)

```bash
export AWS_REGION=us-gov-east-1
export AWS_ACCOUNT_ID=<12-digit-govcloud-account-id>

cp deploy/aws/presets/customer-default.env.example customer-default.env
# edit customer-default.env

sam build -t deploy/aws/template-sam.yaml

set -a && source customer-default.env && set +a
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name notable-analyzer-stack \
  --region us-gov-east-1 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    AwsAccountId="$AWS_ACCOUNT_ID" \
    EcrRepositoryUri="$ECR_REPOSITORY_URI" \
    ImageDigest="$IMAGE_DIGEST" \
    BedrockAnalysisModelId="$BEDROCK_ANALYSIS_MODEL_ID" \
    BedrockAnalysisModelArn="$BEDROCK_ANALYSIS_MODEL_ARN" \
    InputBucketName="$INPUT_BUCKET_NAME" \
    OutputBucketName="$OUTPUT_BUCKET_NAME" \
    CapabilityProfiles=core,rag,analyst_portal \
    SplunkSinkMode=s3 \
    HtmlReportEnabled=false \
    RagEnabled=true \
    RagIngestionEnabled=true \
    SplQueryRagEnabled=true \
    PortalEnabled=true \
    CaseArchiveEnabled=true \
    CaseQaEnabled=true \
    CaseIndexTableName="$CASE_INDEX_TABLE_NAME" \
    PortalUiBucketName="$PORTAL_UI_BUCKET_NAME" \
    PortalJwtIssuer="$PORTAL_JWT_ISSUER" \
    PortalJwtAudience="$PORTAL_JWT_AUDIENCE" \
    PortalCorsAllowedOrigins="$PORTAL_CORS_ALLOWED_ORIGINS" \
    OpenSearchEndpoint="$OPENSEARCH_ENDPOINT" \
    OpenSearchDomainArn="$OPENSEARCH_DOMAIN_ARN" \
    RagTenantId="$RAG_TENANT_ID" \
    CustomerVpcSubnetIds="$CUSTOMER_VPC_SUBNET_IDS" \
    CustomerSecurityGroupIds="$CUSTOMER_SECURITY_GROUP_IDS"
```

Repeat deploys: copy
[`samconfig.customer-default.toml.example`](../../../deploy/aws/presets/samconfig.customer-default.toml.example)
to `samconfig.toml`, fill placeholders, then run `scripts/setup-and-deploy.sh` or
`scripts/setup-and-deploy.ps1`.

## Post-deploy (required for full customer-default)

1. **OpenSearch Phase B** — add the deployed Lambda physical role ARNs to the
   domain access policy before ingest or portal retrieval. See
   [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md).
2. **CMK Phase B (when used)** — add the deployed Lambda physical role ARNs to
   the key policy. See [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md).
3. **SOC KB ingest** — load approved general SOC corpus to S3, publish manifest.
   See [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md).
4. **Splunk dictionary ingest** — required when `SplQueryRagEnabled=true` (portal
   SPL grounding). Same manifest workflow; target index `splunk_dictionary`.
5. **Portal SPA** — build `frontend/analyst-portal`, upload `dist/` to
   `PortalUiBucketName`. See
   [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
6. **Smoke** — run Wave 1 + portal staging checks in
   [`../../testing/TESTING.md`](../../testing/TESTING.md).

```powershell
.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,analyst_portal"
```

## Intentional gaps vs on-prem customer-default

| On-prem setting | GovCloud AWS customer-default preset |
| --- | --- |
| `SPL_QUERY_GENERATION_ENABLED=true` (no live Splunk) | **Off** — no `spl_readonly` profile |
| `CLOSED_TICKET_RAG_ENABLED` / ServiceNow closed-ticket sync | **Not in preset** — parity backlog P3–P7 |
| Postgres + Granite embed/rerank | OpenSearch + Bedrock Titan embed (see approved differences) |
| `CASE_QA_CHAT_HISTORY_ENABLED=true` | Default `false`; enable after DynamoDB chat tables are provisioned |
| nginx Basic Auth front door | Customer edge (CloudFront, ALB, or corporate proxy) + JWT or IAM portal auth |

Track remaining parity work in
[`../../planning/TODOS.md`](../../planning/TODOS.md).

## Next

- **Path B step 8:** [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) — Phase B domain access policy (Lambda physical role ARNs)
- **Path B steps 9–12:** [`../../../README.md`](../../../README.md#path-b-customer-default) (CMK Phase B, KB ingest, portal SPA, smoke)
