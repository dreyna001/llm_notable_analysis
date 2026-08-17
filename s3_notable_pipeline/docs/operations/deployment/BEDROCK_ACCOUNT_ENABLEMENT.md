# GovCloud AWS Bedrock account enablement

Enable and select Bedrock models **before** `sam deploy`. The stack requires
`BedrockAnalysisModelId` and `BedrockAnalysisModelArn` on every deployment; it
does not enable model access in your account.

Region: `us-gov-east-1`. Partition: `aws-us-gov`.

## Models the product uses

| Use | SAM / env | Default product choice |
| --- | --- | --- |
| Notable analysis (required) | `BedrockAnalysisModelId`, `BedrockAnalysisModelArn` | Customer-approved Claude or Nova inference profile |
| Case chunk + RAG embeddings | `CaseQaEmbeddingModel` | `amazon.titan-embed-text-v2:0` (1024 dimensions, locked in v1) |
| Portal chat (optional override) | `PortalChatBedrockModelId`, `PortalChatBedrockModelArn` | Falls back to analysis model when blank |

RAG ingestion and case embed Lambdas need `bedrock:InvokeModel` on the embedding
model ARN. Analyzer and portal need invoke on the analysis (and optional chat) model.

## Enablement checklist

Run in the **target GovCloud account** before deploy:

1. **Confirm region** — active CLI/SDK region is `us-gov-east-1`
2. **Request model access** — in Bedrock console (Model access) or your org’s
   approved process, enable the analysis model or inference profile you plan to use
3. **Enable embedding model** — ensure `amazon.titan-embed-text-v2:0` (or your
   approved alternate documented with engineering) is available if RAG or portal
   case Q&A is enabled
4. **Record IDs and ARNs** — copy exact strings for SAM parameters (see below)
5. **Verify invoke** — from an approved role in the account:

```bash
export AWS_REGION=us-gov-east-1
export MODEL_ID="<your-approved-model-or-profile-id>"

aws bedrock list-foundation-models --region us-gov-east-1 \
  --query "modelSummaries[?modelId=='${MODEL_ID}'].modelId" --output text

aws bedrock list-inference-profiles --region us-gov-east-1 \
  --query "inferenceProfileSummaries[?contains(inferenceProfileId, 'claude')].inferenceProfileId" \
  --output table
```

6. **Map to SAM** — set deploy parameters (guided deploy, `samconfig.toml`, or env file)
7. **Scope IAM** — template grants `bedrock:InvokeModel` only on ARNs you pass; mismatched ID/ARN pairs fail closed at deploy or runtime

## Choosing `BedrockAnalysisModelId` and `BedrockAnalysisModelArn`

| Model type | `BedrockAnalysisModelId` example | `BedrockAnalysisModelArn` pattern |
| --- | --- | --- |
| Foundation model | `amazon.nova-pro-v1:0` | `arn:aws-us-gov:bedrock:us-gov-east-1::foundation-model/amazon.nova-pro-v1:0` |
| Inference profile | `us-gov.anthropic.claude-sonnet-4-20250514-v1:0` | `arn:aws-us-gov:bedrock:us-gov-east-1:<account-id>:inference-profile/us-gov.anthropic.claude-sonnet-4-20250514-v1:0` |

Rules:

- **ID and ARN must refer to the same deploy-time choice**
- Use the **inference profile ARN** when routing through a profile
- GovCloud model IDs and profiles differ from commercial — do not copy commercial ARNs

## Embedding model (RAG + portal)

`CaseQaEmbeddingModel` defaults to `amazon.titan-embed-text-v2:0`. Runtime config
requires `CASE_QA_VECTOR_DIMENSIONS=1024` for Titan V2 in v1.

If you change embedding models, plan a **full re-embed** of OpenSearch corpora and
case chunks; mixed vectors in one index are unsupported.

## Portal chat model override

When `PortalChatBedrockModelId` is set, also set `PortalChatBedrockModelArn` to
the matching ARN. Portal IAM is scoped to that ARN in addition to the analysis model
when override is present.

## VPC Lambdas and Bedrock

Lambdas in a VPC reach Bedrock via NAT or a
`com.amazonaws.us-gov-east-1.bedrock-runtime` interface endpoint. See
[`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md).

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
