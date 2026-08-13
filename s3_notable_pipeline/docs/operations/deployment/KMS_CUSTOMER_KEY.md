# GovCloud AWS customer-managed KMS (CMK)

Optional but common for production. When `CustomerKmsKeyArn` is set, the SAM
template encrypts supported data-plane resources with that CMK instead of AWS
owned keys.

The product does **not** create the CMK or key policy. You provision the key,
grant the product Lambda roles (and OpenSearch when used), then pass the ARN at deploy.

Region: `us-gov-east-1`. Partition: `aws-us-gov`.

## When to use a CMK

| Scenario | Recommendation |
| --- | --- |
| Dev/staging core-only | AWS owned keys (leave `CustomerKmsKeyArn` blank) |
| Production or regulated customer | CMK with explicit key policy |
| OpenSearch encryption at rest | Same CMK as `CustomerKmsKeyArn` when aligning policies |

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

## Key policy pattern (after first deploy)

Replace placeholders with your account, key id, and Lambda role ARNs from the
CloudFormation stack **after** `sam deploy`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowKeyAdministration",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws-us-gov:iam::<account-id>:role/<key-admin-role>"
      },
      "Action": "kms:*",
      "Resource": "*"
    },
    {
      "Sid": "AllowProductLambdaUse",
      "Effect": "Allow",
      "Principal": {
        "AWS": [
          "arn:aws-us-gov:iam::<account-id>:role/<stack>-AnalyzerFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack>-CaseEmbedFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack>-RagIngestionFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack>-PortalApiFunctionRole-<suffix>",
          "arn:aws-us-gov:iam::<account-id>:role/<stack>-DispositionSyncFunctionRole-<suffix>"
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
          "kms:ViaService": "es.us-gov-east-1.amazonaws.com"
        }
      }
    }
  ]
}
```

Include only Lambda roles that exist for your enabled capabilities.

Lookup roles:

```bash
aws cloudformation describe-stack-resources \
  --stack-name notable-analyzer-stack \
  --region us-gov-east-1 \
  --query "StackResources[?ResourceType=='AWS::IAM::Role'].PhysicalResourceId" \
  --output table
```

## Two-phase CMK rollout (recommended)

**Phase A — create key:** key admin creates CMK with admin-only policy.

**Phase B — after SAM deploy:** add product Lambda role ARNs and OpenSearch service
principal; update key policy; verify encrypt/decrypt from a test notable.

## Create key (CLI sketch)

```bash
export AWS_REGION=us-gov-east-1
aws kms create-key \
  --region "$AWS_REGION" \
  --description "notable-analyzer data plane" \
  --query 'KeyMetadata.Arn' --output text
```

Create alias, enable rotation per org policy, then pass ARN as `CustomerKmsKeyArn`.

## Validation

1. S3 buckets show SSE-KMS with your key
2. Test notable processing succeeds
3. SQS send/receive and DynamoDB writes succeed (no `KMS.AccessDeniedException` in logs)
4. OpenSearch domain reports encryption at rest with the same CMK when aligned

## Related docs

- [`VPC_NETWORK_PREREQUISITES.md`](VPC_NETWORK_PREREQUISITES.md)
- [`OPENSEARCH_PROVISIONING.md`](OPENSEARCH_PROVISIONING.md)
- [`../security/SECURITY_OPERATIONS.md`](../security/SECURITY_OPERATIONS.md)
