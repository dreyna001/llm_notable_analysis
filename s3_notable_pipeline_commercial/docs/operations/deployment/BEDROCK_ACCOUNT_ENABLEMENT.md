# Commercial AWS Bedrock account enablement

Enable and select Bedrock models before infrastructure deployment. Path B Terraform requires
`BedrockAnalysisModelId` and `BedrockAnalysisModelArn` on every deployment; it
does not enable model access in your account.

**Prerequisites:** root README sections **2–3**. **Path B:** record model ID/ARN
values in `deploy/terraform/customer_default/terraform.tfvars`.

Partition `aws`, region `us-east-1` — see
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md#deployment-boundary).

## Models the product uses

| Use | Former SAM name / Terraform equivalent | Default product choice |
| --- | --- | --- |
| Notable analysis (required) | `BedrockAnalysisModelId`, `BedrockAnalysisModelArn` | Customer-approved Claude or Nova inference profile |
| Case chunk + RAG embeddings | `CaseQaEmbeddingModel` | `amazon.titan-embed-text-v2:0` (1024 dimensions, locked in v1) |
| Portal chat (optional override) | `PortalChatBedrockModelId`, `PortalChatBedrockModelArn` | Falls back to analysis model when blank |

RAG ingestion, case embed, analyzer, and portal Lambdas receive
`bedrock:InvokeModel` on the configured embedding model when private vector
retrieval is configured. Analyzer and portal also receive invoke on their
configured analysis/chat models.

## Enablement checklist

Run in the **target commercial account** before deploy:

1. **Confirm region** — active CLI/SDK region is `us-east-1`
2. **Request model access** — in Bedrock console (Model access) or your org's
   approved process, enable the analysis model or inference profile you plan to use
3. **Enable embedding model** — ensure `amazon.titan-embed-text-v2:0` (or your
   approved alternate documented with engineering) is available if RAG or portal
   case Q&A is enabled
4. **Record IDs and ARNs** — copy exact strings for deployment inputs (see below)
5. **Verify invoke** — from an approved role in the account, confirm your
   **customer-approved** model or inference profile is listed and invocable.
   The examples below are discovery commands only; they do not choose deploy values.

```bash
export AWS_REGION=us-east-1
export MODEL_ID="<your-approved-model-or-profile-id>"

aws bedrock list-foundation-models --region us-east-1 \
  --query "modelSummaries[?modelId=='${MODEL_ID}'].modelId" --output text

# Inference profiles (common for Claude):
aws bedrock list-inference-profiles --region us-east-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude')].inferenceProfileId" \
  --output table
```

`scripts/setup-and-deploy.ps1` runs illustrative readiness probes (Nova, Claude).
Those probes only confirm list APIs succeed — they are **not** the deploy-time
model choice. Record the exact customer-approved `BedrockAnalysisModelId` and
`BedrockAnalysisModelArn` pair. Path B maps them to
`bedrock_analysis_model_id` and `bedrock_analysis_model_arn`.

6. **Map inputs** — use Path B `terraform.tfvars`; Paths A/C use legacy SAM parameters
7. **Scope IAM** — IaC grants `bedrock:InvokeModel` only on ARNs you pass; mismatched ID/ARN pairs fail closed at deploy or runtime

## Choosing `BedrockAnalysisModelId` and `BedrockAnalysisModelArn`

The table below shows **format patterns** only. Replace every example with the
exact ID and ARN your customer approved for this deployment. A Claude inference
profile in the table is not interchangeable with a Nova foundation model, and
setup-script probe strings (such as `claude-sonnet-4-6`) may differ from the
profile ID you deploy.

| Model type | `BedrockAnalysisModelId` example | `BedrockAnalysisModelArn` pattern |
| --- | --- | --- |
| Foundation model | `amazon.nova-pro-v1:0` | `arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0` |
| Inference profile | `us.anthropic.claude-sonnet-4-20250514-v1:0` | `arn:aws:bedrock:us-east-1:<account-id>:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0` |

Rules:

- **ID and ARN must refer to the same deploy-time choice** — the template
  validates both are non-empty and IAM is scoped to the ARNs you pass
- Use the **inference profile ARN** when routing through a profile and complete
  the geographic cross-region IAM step below
- Do not hardcode unapproved model IDs in shared presets; keep them in customer env files only
- Setup/deploy readiness probes that list Nova or Claude availability are hints only; mismatched ID/ARN pairs still fail closed at deploy or runtime

### Geographic cross-region inference profiles

For a geographic profile, AWS also requires `bedrock:InvokeModel` on the
profile's foundation model in the source region and every listed destination
region. Read the exact ARNs from `GetInferenceProfile` and pass them, with no
wildcards, as a comma-separated `BedrockAnalysisInferenceProfileFoundationModelArns`
value:

```bash
aws bedrock get-inference-profile \
  --region us-east-1 \
  --inference-profile-identifier "$MODEL_ID" \
  --query 'models[].modelArn' \
  --output text
```

The template restricts those foundation-model grants with
`bedrock:InferenceProfileArn`. Portal overrides have independent IAM: when a
chat or vision override is set, pass its model ARNs through
`PortalChatInferenceProfileFoundationModelArns` or
`PortalChatVisionInferenceProfileFoundationModelArns`, even if that override
reuses the analysis profile ARN. Leave these parameters blank for direct
foundation-model invocation. Global profiles require a different
`aws:RequestedRegion=unspecified` policy and are not supported by these
geographic-profile parameters.

## Embedding model (RAG + portal)

`CaseQaEmbeddingModel` defaults to `amazon.titan-embed-text-v2:0`. Runtime config
requires `CASE_QA_VECTOR_DIMENSIONS=1024` for Titan V2 in v1.

If you change embedding models, plan a **full re-embed** of OpenSearch corpora and
case chunks; mixed vectors in one index are unsupported.

## Portal chat model override

When `PortalChatBedrockModelId` is set, also set `PortalChatBedrockModelArn` to
the matching ARN. Portal IAM is scoped to that ARN instead of the analysis model
when override is present. If it is a geographic profile, also set
`PortalChatInferenceProfileFoundationModelArns`.

## VPC Lambdas and Bedrock

Lambdas in a VPC reach Bedrock via NAT or a `com.amazonaws.us-east-1.bedrock-runtime`
interface endpoint — see [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md#nat-gateway-vs-vpc-endpoints).

## Validation after deploy

1. Upload a test notable to `incoming/`; confirm markdown/JSON under `reports/`
2. CloudWatch logs for `notable-analyzer-s3` show no `AccessDeniedException` from Bedrock
3. With RAG enabled, confirm `metadata.rag_status` in JSON output (success, no_match, or explicit degraded — not auth failures)
4. With portal enabled, pinned-case chat returns within API timeout without model errors

## Next

- **Path A step 2:** [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md)
- **Path B step 5:** [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md)
- **Path C:** [`PORTAL_JWT_IDENTITY.md`](PORTAL_JWT_IDENTITY.md) when `analyst_portal` is enabled; otherwise [`DEPLOYMENT_IMAGE_STEPS.md`](DEPLOYMENT_IMAGE_STEPS.md) — [`../../../README.md`](../../../README.md#path-c-custom-profiles)
- Tuning after enablement: [`../llm/LLM_INFERENCE_OPERATIONS.md`](../llm/LLM_INFERENCE_OPERATIONS.md)
