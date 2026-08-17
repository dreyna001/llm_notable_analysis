# Commercial AWS customer-managed KMS (CMK)

Optional but common for production. When `CustomerKmsKeyArn` is set, the SAM
template encrypts supported data-plane resources with that CMK instead of AWS
owned keys. The product does **not** create the CMK or key policy — you provision
the key, grant Lambda roles (and OpenSearch when used), then pass the ARN at deploy.

Partition `aws`, region `us-east-1` — see
[`COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md`](COMMERCIAL_AWS_CUSTOMER_CONFIGURATION.md#deployment-boundary).

## When to use a CMK

| Scenario | Recommendation |
| --- | --- |
| Dev/staging core-only | AWS owned keys (leave `CustomerKmsKeyArn` blank) |
| Production or regulated customer | CMK with explicit key policy |
| OpenSearch encryption at rest | Same CMK as `CustomerKmsKeyArn`; **create the CMK before the OpenSearch domain** when the domain uses it |

**Path B step 1** (optional CMK before OpenSearch when the domain encrypts with it):
[`../../../README.md`](../../../README.md#path-b-customer-default).

Resources encrypted when `CustomerKmsKeyArn` is set (template behavior):

- S3 input, output, and portal UI buckets (bucket default encryption)
- SQS queues (analyzer, embed, RAG ingestion, DLQs)
- DynamoDB tables created by the stack (CaseIndex, idempotency, disposition, chat history when enabled)
- CloudWatch log groups for product Lambdas

OpenSearch domain encryption uses `KmsKeyId` at **domain create time** — use the
same CMK ARN you pass to SAM when possible.

## SAM parameters

| Parameter | Purpose |
| --- | --- |
| `CustomerKmsKeyArn` | CMK ARN — enables encryption on stack resources above |
| `CustomerKmsKeyAdminRoleArn` | Optional; recorded as stack output for key administrators |

Lambda execution roles receive managed policies from the template:

- **Read:** `kms:Decrypt`, `kms:DescribeKey`
- **Write (analyzer, case embed):** also `kms:GenerateDataKey`

## Key policy pattern (Phase B — after first deploy)

Replace placeholders with your account, key id, and **physical** Lambda role
names from the CloudFormation stack (logical ids such as
`NotableAnalyzerFunctionRole` map to suffixed physical role names):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowKeyAdministration",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<account-id>:role/<key-admin-role>"
      },
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "AllowProductLambdaUse",
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-NotableAnalyzerFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-CaseEmbedFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-RagIngestionFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-PortalApiFunctionRole>",
          "arn:aws:iam::<account-id>:role/<physical-role-name-for-DispositionSyncFunctionRole>"
        ]
      },
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey"
      ],
      "Resource": "*"
    },
    {
      "Sid": "AllowOpenSearchService",
      "Effect": "Allow",
      "Principal": {
        "Service": "es.amazonaws.com"
      },
      "Action": [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:CreateGrant"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "es.us-east-1.amazonaws.com"
        }
      }
    }
  ]
}
```

Include only Lambda roles that exist for your enabled capabilities.

Copy physical role names from the stack (same command as OpenSearch Phase B):
[`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md#two-phase-access-policy-required).

## Two-phase CMK rollout (recommended)

**Phase A — create key:** key admin creates CMK with admin-only policy and
OpenSearch service principal if the domain will use this key at create time.

**Phase B — after `sam deploy`:** add product Lambda **physical** role ARNs from
`describe-stack-resources`; update key policy; verify encrypt/decrypt from a test
notable.

If you set `CustomerKmsKeyArn` **before** Lambda roles exist, leave a break-glass
admin statement and tighten after deploy (**Path B step 9**).

## Create key (CLI sketch)

```bash
export AWS_REGION=us-east-1
aws kms create-key \
  --region "$AWS_REGION" \
  --description "notable-analyzer data plane" \
  --query 'KeyMetadata.Arn' --output text
```

Create alias, enable rotation per org policy, then pass ARN as `CustomerKmsKeyArn`.

## Validation

1. S3 buckets show SSE-KMS with your key (bucket encryption settings)
2. Test notable processing succeeds (analyzer decrypts/encrypts via CMK)
3. SQS send/receive and DynamoDB writes succeed (no `KMS.AccessDeniedException` in logs)
4. OpenSearch domain reports encryption at rest with the same CMK when aligned

## Next

- **Path B step 1 complete (or skipped):** [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md) (step 2)
- **Path B step 9 (CMK Phase B):** [`KNOWLEDGE_BASE_OPERATIONS.md`](../rag/KNOWLEDGE_BASE_OPERATIONS.md) after key policy update
- **Path C:** [`../../../README.md`](../../../README.md#path-c-custom-profiles) when OpenSearch or CMK applies
