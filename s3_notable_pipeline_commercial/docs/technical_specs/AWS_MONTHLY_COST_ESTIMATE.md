# AWS monthly cost estimate (commercial `us-east-1`)

Planning worksheet for the **customer-default** commercial AWS deployment
(`CapabilityProfiles=core,rag,analyst_portal`) in `us-east-1`. Use this document
for budget conversations and capacity planning. It is **not** a quote from AWS.

**Last updated:** 2026-08-19  
**Region:** `us-east-1`  
**Currency:** USD

## What this covers

| Included | Excluded |
| --- | --- |
| Bedrock inference (analysis + portal chat) | Analyst salaries, Splunk licensing, IdP licensing |
| Bedrock Titan embeddings (case/RAG) | Customer edge (CloudFront, WAF, Route 53) unless you add them |
| Stack-provisioned AWS services (Lambda, S3, SQS, DynamoDB, API Gateway, CloudWatch) | One-time migration or professional services |
| Customer-provisioned OpenSearch domain (VPC) | Cross-region DR |
| NAT gateway **or** interface VPC endpoints (assumption documented below) | Prompt-cache savings (assumed **off** unless noted) |
| Optional customer CMK API charges (small) | Extended thinking / reasoning tokens unless noted |

Authoritative deployment inventory:
[`../operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md`](../operations/deployment/CUSTOMER_OWNERSHIP_AND_PRODUCT_SCOPE.md).

## Baseline workload

| Input | Value used in this worksheet |
| --- | --- |
| Alerts per day | 400 |
| Alerts per month | 12,000 (30-day month) |
| Analysts | 5 (24/7 SOC, three shifts) |
| Deployment preset | `core,rag,analyst_portal` |
| Analysis model | One Bedrock model for auto-analysis **and** portal chat unless overridden |
| Extended thinking | **Off** for Claude; **off** for Nova unless a row says otherwise |
| Prompt caching | **Off** (conservative) |
| Retention | 90 days for cases/chats where configured; KB does not age off |

Every alert is assumed to receive **one automated analysis call** plus analyst
portal chat. Chat is synchronous (29s API cap per turn).

## Model list prices (`us-east-1`, on-demand)

Verify live rates on [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/)
before contract or budget lock.

| Model | Model ID (examples) | Input / 1M | Output / 1M | Context | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| Amazon Nova Pro v1 | `amazon.nova-pro-v1:0` | $0.80 | $3.20 | 300K | Stable; repo default in tests/docs |
| Amazon Nova 2 Lite | `us.amazon.nova-2-lite-v1:0` | ~$0.33* | ~$2.75* | 1M | US inference profile; reasoning configurable |
| Amazon Nova 2 Pro (Preview) | preview profile | $1.25 | $10.00 | 1M | Preview — not for sole production dependency |
| Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` | $3.00 | $15.00 | 1M | Flat pricing across full context window |
| Claude Haiku 4.5 | `anthropic.claude-haiku-4-5-...` | $1.00 | $5.00 | 200K | Strong quality/cost; tight context for huge alerts |
| Titan Embed Text v2 | `amazon.titan-embed-text-v2:0` | $0.02 | — | 8K/chunk | Case + RAG embeddings |

\* Nova 2 Lite global list is $0.30 / $2.50; US geo profile adds ~10%.

Titan embeddings at this volume are **&lt;$25/month** in all scenarios below.

## Cost formulas

### Per alert — automated analysis (one primary Bedrock call)

```
analysis_cost = alerts_per_month × (
    input_tokens × input_rate_per_token +
    output_tokens × output_rate_per_token
)
```

Add **~10–20%** if schema repair or transport fallback triggers extra calls
(see [`../operations/llm/LLM_INFERENCE_OPERATIONS.md`](../operations/llm/LLM_INFERENCE_OPERATIONS.md)).

### Per month — analyst portal chat

```
chat_cost = alerts_per_month × questions_per_alert × (
    chat_input_tokens × input_rate_per_token +
    chat_output_tokens × output_rate_per_token
)
```

Portal chat defaults: `CASE_QA_MAX_ANSWER_TOKENS=800` (SAM default). Lighter
usage scenarios below assume shorter answers and smaller pasted log excerpts.

### Infrastructure (fixed + variable)

| Component | Median month | Heavy month | Driver |
| --- | ---: | ---: | --- |
| OpenSearch (`t3.small.search` × 2, 50 GiB gp3) | ~$105 | ~$130 | 24/7 domain; storage growth |
| NAT gateway (1 AZ) or VPC endpoints | ~$45–$90 | ~$45–$120 | Private Lambda egress to Bedrock/OpenSearch |
| Lambda + SQS + API Gateway + DynamoDB | ~$40 | ~$120 | Portal chat volume, embed jobs |
| S3 + CloudWatch Logs + KMS + ECR | ~$30 | ~$80 | Retention, log volume, image storage |
| **Infrastructure subtotal** | **~$220** | **~$450** | Rounded planning band |

OpenSearch is **customer-provisioned**; sizing is the largest fixed lever after
model choice. See [`../operations/deployment/OPENSEARCH_PROVISIONING.md`](../operations/deployment/OPENSEARCH_PROVISIONING.md).

## Scenario A — heavy analyst usage

Assumes long investigations, frequent chat, and larger log paste-back.

| Token assumption | Median | Realistic worst |
| --- | ---: | ---: |
| Auto-analysis input / output per alert | 80K / 3K | 300K / 6K |
| Analyst questions per alert | 8 | 12 |
| Chat input / output per question | 7K / 500 | 12K / 800 |

### Scenario A totals (model + infrastructure)

| Model | Median / month | Realistic worst / month |
| --- | ---: | ---: |
| **Nova Pro v1** | **~$1,800** | **~$5,600** |
| **Claude Sonnet 4.6** | **~$6,350** | **~$20,300** |
| Nova 2 Lite (reasoning off) | ~$1,000 | ~$2,900 |
| Nova 2 Pro Preview | ~$3,100 | ~$10,000 |

**Budget bands:** Sonnet plan **$7,000** normal with alerts at **$18K–$22K**.
Nova Pro plan **$2,000** normal with alerts at **$5K–$6K**.

Nova Pro v1 **cannot** ingest full 750K-token alert payloads (300K context cap).
Use truncation, pre-summarization, or a 1M-context model for log-heavy alerts.

## Scenario B — lighter analyst usage (recommended planning default)

Assumes smaller typical Splunk payloads, shorter investigations, and modest
log paste-back (focused excerpts, not bulk exports).

| Token assumption | Median | Realistic worst |
| --- | ---: | ---: |
| Auto-analysis input / output per alert | 25K / 1.5K | 60K / 3K |
| Analyst questions per alert | 2 | 4 |
| Chat input / output per question | 3K / 400 | 5K / 500 |

### Scenario B totals (model + infrastructure)

| Model | Median / month | Realistic worst / month |
| --- | ---: | ---: |
| **Nova Pro v1** | **~$560** | **~$1,300** |
| **Claude Sonnet 4.6** | **~$1,600** | **~$4,300** |
| Nova 2 Lite (reasoning off) | ~$400 | ~$900 |
| Nova 2 Lite (medium reasoning, analysis only) | ~$500 | ~$1,100 |
| Nova 2 Pro Preview | ~$900 | ~$2,500 |

**Budget bands:** Sonnet **$1,750** normal / **$4,500** heavy. Nova Pro **$600**
normal / **$1,500** heavy.

### Worked example — Sonnet 4.6, Scenario B median

```
Auto:  12,000 × (25,000 × $3/1M + 1,500 × $15/1M) ≈ $1,170
Chat:  24,000 turns × (3,000 × $3/1M + 400 × $15/1M)   ≈   $360
Infra:                                                  ≈   $220
Total:                                                  ≈ $1,750
```

## Model selection notes

| Goal | Recommendation |
| --- | --- |
| Lowest cost, production-stable | **Nova 2 Lite** (`us.amazon.nova-2-lite-v1:0`), reasoning **low/off** for chat, **medium** optional for analysis |
| Stay on Nova Pro v1 | Acceptable at Scenario B costs; upgrade path is Nova 2 Lite, not Nova 2 Pro Preview alone |
| Highest analysis confidence | **Sonnet 4.6**; route top ~10% severity alerts to Sonnet and remainder to Nova 2 Lite to blend cost and quality |
| Avoid for auto-analysis today | Nova 2 Pro **Preview** as sole production model; Haiku 4.5 for alerts &gt;200K tokens without truncation |

**Preview** means AWS may change behavior, pricing, quotas, or availability before
general availability. Treat Nova 2 Pro Preview as evaluation-only until GA.

## Recommended payload and chat limits (product TODO)

Current code limits are below the workload described in planning sessions.
Track these before production at log-heavy volume:

| Setting | Today (SAM/code) | Recommended |
| --- | --- | --- |
| `MaxDecompressedInputBytes` | 1 MiB | **3 MiB** |
| Alert line cap | none | **15,000 lines** (with token budget) |
| Alert token budget (pre-Bedrock) | none | **750,000 estimated tokens** (truncate + flag) |
| `CaseQaMaxQuestionChars` | 2,000 | **60,000** |
| Analyst log paste cap | none | **200 lines** and **60,000 characters** (whichever first) |
| `CaseArchiveMaxAlertBytes` | 256 KiB | Raise to match archive policy |
| Chat history retention | 30 days default | **90 days** (customer operationalization) |

At ~300 characters per Splunk line, **200 lines ≈ 60,000 characters**, which
fits portal synthesis budgets without encouraging full log dumps.

## Recalibrate after month one

Replace worksheet assumptions with CloudWatch/Bedrock metrics:

1. `InputTokenCount` / `OutputTokenCount` on analyzer and portal Lambdas.
2. P50 / P95 alert payload size at ingest (bytes and estimated tokens).
3. Portal chat turns per case (DynamoDB chat tables).
4. OpenSearch storage (`_cat/indices`) and query latency.
5. NAT or VPC endpoint data processing GB.

Update this document when measured P50/P95 diverges by more than **25%** from the
active scenario.

## Related docs

| Topic | Doc |
| --- | --- |
| Bedrock model enablement | [`../operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md`](../operations/deployment/BEDROCK_ACCOUNT_ENABLEMENT.md) |
| LLM timeouts and call paths | [`../operations/llm/LLM_INFERENCE_OPERATIONS.md`](../operations/llm/LLM_INFERENCE_OPERATIONS.md) |
| OpenSearch sizing | [`../operations/deployment/OPENSEARCH_PROVISIONING.md`](../operations/deployment/OPENSEARCH_PROVISIONING.md) |
| Retention | [`../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md`](../operations/platform/FILE_DROP_AND_RETENTION_OPERATIONS.md) |
| Customer-default deploy | [`../operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md`](../operations/deployment/COMMERCIAL_AWS_CUSTOMER_DEFAULT_DEPLOYMENT.md) |
