# Commercial AWS application core module

This child module deploys the native Terraform replacement for the customer-default SAM core:

- analyzer, case embedding, and RAG ingestion Lambda functions from one digest-pinned ECR image;
- deterministic least-privilege IAM roles for direct OpenSearch and KMS policy wiring;
- analyzer, embedding, and ingestion queues, dead-letter queues, and event source mappings;
- private input and output buckets with encryption, versioning, lifecycle rules, and S3-to-SQS notifications;
- the CaseIndex DynamoDB table used by case archive, embedding, and the analyst portal; and
- retained log groups and queue, DLQ, and Lambda error alarms.

The module does not create network, KMS, ECR, OpenSearch, portal/API, ServiceNow, Splunk read-only, or action-gated resources. The `customer_default` root module owns composition with those layers.

## Requirements

- Terraform 1.6 or later
- AWS provider 6.x
- commercial AWS partition, `us-east-1`
- an ECR image URI pinned as `repository@sha256:digest`
- existing private subnets and security groups for the customer-default private path
- an existing VPC-only OpenSearch domain and approved Bedrock model

## Example

```hcl
module "application_core" {
  source = "../application_core"

  name_prefix = "notable-prod"
  image_uri   = "123456789012.dkr.ecr.us-east-1.amazonaws.com/notable@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

  input_bucket_name  = "customer-notable-input"
  output_bucket_name = "customer-notable-output"

  subnet_ids        = module.network.private_subnet_ids
  security_group_ids = [module.network.lambda_security_group_id]
  kms_key_arn        = module.kms.key_arn

  bedrock_analysis_model_id   = var.bedrock_analysis_model_id
  bedrock_analysis_model_arn  = var.bedrock_analysis_model_arn
  opensearch_endpoint         = module.opensearch.endpoint
  opensearch_domain_arn       = module.opensearch.domain_arn
  rag_tenant_id               = var.rag_tenant_id

  tags = var.tags
}
```

The defaults enable `core`, general RAG, RAG ingestion, case archiving, and Case Q&A embedding. The core profile leaves action-gated side-effect idempotency disabled and does not create its DynamoDB table.

## External bucket handoffs

When `rag_source_bucket_name` is null, the module configures the managed input bucket to publish objects under `rag-sources/manifests/` to the ingestion queue. When an external source bucket is supplied, the customer must configure that bucket's notification using `rag_ingestion_queue_arn`; the queue policy is already scoped to that bucket and account.

When `case_archive_bucket_name` is null, cases use the managed output bucket. An external archive bucket remains customer-managed, including its encryption, lifecycle, and bucket policy.

## Composition outputs

The root and portal modules should consume:

- `case_index_table_name` and `case_index_table_arn`;
- `case_embed_queue_url` and `case_embed_queue_arn`;
- `analyzer_role_arn`, `case_embed_role_arn`, and `rag_ingestion_role_arn`;
- `opensearch_read_role_arns` and `opensearch_write_role_arns`; and
- `kms_lambda_role_arns`.

The IAM role names are deterministic from `name_prefix`, so the root can construct the same ARNs for KMS and OpenSearch policies without a second deployment phase.
