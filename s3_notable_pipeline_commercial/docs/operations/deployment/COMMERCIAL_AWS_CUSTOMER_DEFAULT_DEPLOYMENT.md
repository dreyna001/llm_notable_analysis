# Commercial AWS customer-default deployment

One-shot SAM preset for the on-prem **customer-default** bundle on commercial
AWS (`aws`, `us-east-1`):

- `CapabilityProfiles=core,rag,analyst_portal`
- General SOC RAG + Splunk dictionary grounding for portal chat
- Case archive, CaseIndex, read-only portal API, pinned-case Q&A
- **No** `spl_readonly` (no first-pass SPL generation or live Splunk queries)
- **No** closed-ticket RAG (planned in parity plan phases P3–P6)

On-prem normative reference:
[`../../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md`](../../../../llm_notable_analysis_onprem_systemd/docs/operations/deployment/CUSTOMER_DEFAULT_DEPLOYMENT.md)

## Preset files (copy and fill)

| File | Purpose |
| --- | --- |
| [`../../../deploy/aws/presets/customer-default.env.example`](../../../deploy/aws/presets/customer-default.env.example) | Placeholder env file; source before `sam deploy --parameter-overrides` |
| [`../../../deploy/aws/presets/samconfig.customer-default.toml.example`](../../../deploy/aws/presets/samconfig.customer-default.toml.example) | Copy to project-root `samconfig.toml` for repeat deploys |

Image build and ECR push still follow
[`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) before deploy.

## Step 0: Customer prerequisites (required for this preset)

Complete these runbooks **before** `sam deploy`:

| Order | Runbook | Purpose |
| --- | --- | --- |
| 1 | [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md) | Private subnets, NAT or VPC endpoints, Lambda security groups |
| 2 | [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) | VPC-only OpenSearch domain (stack does not create it) |
| 3 | [`BEDROCK_ACCOUNT_ENABLEMENT.md`](BEDROCK_ACCOUNT_ENABLEMENT.md) | Analysis + embedding model IDs/ARNs |
| 4 | [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) | Issuer, audience, analyst grant, CORS |
| Optional | [`KMS_CUSTOMER_KEY.md`](KMS_CUSTOMER_KEY.md) | Customer CMK for production encryption |

Copy into `customer-default.env`:

- `OpenSearchEndpoint`, `OpenSearchDomainArn`, `RagTenantId`
- `CustomerVpcSubnetIds`, `CustomerSecurityGroupIds`
- `BedrockAnalysisModelId`, `BedrockAnalysisModelArn`
- `PortalJwtIssuer`, `PortalJwtAudience`, `PortalRequiredAnalystRole` or `PortalRequiredAnalystScope`, `PortalCorsAllowedOrigins`
- `CustomerKmsKeyArn` when using a CMK

Indexes (`soc_knowledge`, `splunk_dictionary`, `case_chunks`) are created
automatically on first ingest or case embed; do not hand-provision mappings.

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

## Customer values checklist

Collect these before deploy (see also
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md)):

| Area | Parameters |
| --- | --- |
| Image | `EcrRepositoryUri`, `ImageDigest`, `AwsAccountId` |
| Bedrock | `BedrockAnalysisModelId`, `BedrockAnalysisModelArn` |
| S3 | `InputBucketName`, `OutputBucketName` |
| Portal | `CaseIndexTableName`, `PortalUiBucketName`, `PortalJwtIssuer`, `PortalJwtAudience`, `PortalCorsAllowedOrigins` |
| OpenSearch | `OpenSearchEndpoint`, `OpenSearchDomainArn`, `RagTenantId`, `CustomerVpcSubnetIds`, `CustomerSecurityGroupIds` — from [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md) |
| Indexes (defaults OK) | `OpenSearchSocIndex=soc_knowledge`, `OpenSearchSplunkIndex=splunk_dictionary`, `OpenSearchCaseIndex=case_chunks` |

Optional tuning left at product defaults unless customer policy requires changes:
`CaseQaEmbeddingModel`, `RagMaxSnippets`, `CaseRetentionDays`, `LogRetentionDays`.

## Deploy (fast path)

```bash
export AWS_REGION=us-east-1
export COMMERCIAL_AWS_ACCOUNT_ID=<12-digit-account-id>

cp deploy/aws/presets/customer-default.env.example customer-default.env
# edit customer-default.env

sam build -t deploy/aws/template-sam.yaml

set -a && source customer-default.env && set +a
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name notable-analyzer-stack \
  --region us-east-1 \
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

1. **Portal SPA** — build `frontend/analyst-portal`, upload `dist/` to
   `PortalUiBucketName`. See
   [`../analyst_portal/ANALYST_PORTAL_OPERATIONS.md`](../analyst_portal/ANALYST_PORTAL_OPERATIONS.md).
2. **SOC KB ingest** — load approved general SOC corpus to S3, publish manifest.
   See [`../rag/KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md).
3. **Splunk dictionary ingest** — required when `SplQueryRagEnabled=true` (portal
   SPL grounding). Same manifest workflow; target index `splunk_dictionary`.
4. **Smoke** — run Wave 1 + portal staging checks in
   [`../../testing/TESTING.md`](../../testing/TESTING.md).

```powershell
.\scripts\test-pipeline.ps1 -Wave1Smoke -ExpectCapabilityProfiles "core,rag,analyst_portal"
```

## Intentional gaps vs on-prem customer-default

| On-prem setting | Commercial AWS customer-default preset |
| --- | --- |
| `SPL_QUERY_GENERATION_ENABLED=true` (no live Splunk) | **Off** — no `spl_readonly` profile |
| `CLOSED_TICKET_RAG_ENABLED` / ServiceNow closed-ticket sync | **Not in preset** — parity plan P3–P6 |
| Postgres + Granite embed/rerank | OpenSearch + Bedrock Titan embed (see approved differences) |
| `CASE_QA_CHAT_HISTORY_ENABLED=true` | Default `false`; enable after DynamoDB chat tables are provisioned |
| nginx Basic Auth front door | Customer edge (CloudFront, ALB, or corporate proxy) + JWT or IAM portal auth |

Track remaining parity work in
[`../../planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md`](../../planning/COMMERCIAL_AWS_ONPREM_CUSTOMER_DEFAULT_PARITY_PLAN.md).

## Related docs

- [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md)
- [`../platform/CAPABILITY_PROFILES.md`](../platform/CAPABILITY_PROFILES.md)
- [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- [`../rag/RAG_OPERATIONS.md`](../rag/RAG_OPERATIONS.md)
