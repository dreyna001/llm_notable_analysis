# Commercial AWS analyst portal Terraform module

This child module deploys the customer-default analyst portal with native Terraform. It does not invoke SAM or CloudFormation and does not create the shared network, KMS key, ECR repository, OpenSearch domain, output bucket, CaseIndex table, or case-embedding queue.

## Creates

- a digest-pinned portal Lambda and deterministic execution role
- an API Gateway v2 HTTP API with public health/static routes and protected API routes
- a fail-closed JWT authorizer by default; AWS IAM authorization is also supported
- a private, encrypted, versioned S3 bucket for the portal SPA
- optional encrypted DynamoDB chat session/message tables; disabled by default
- a retained Lambda log group plus Lambda-error and API-5xx alarms

The core application module must provide the output bucket, CaseIndex name/ARN, and case-embedding queue URL. The foundation modules must provide the VPC, KMS, OpenSearch, and immutable ECR image dependencies.

## Example

```hcl
module "portal" {
  source = "../application_portal"

  aws_account_id = var.aws_account_id
  aws_region     = var.aws_region
  name_prefix    = var.name_prefix
  image_uri      = var.image_uri

  subnet_ids        = module.foundation.subnet_ids
  security_group_ids = module.foundation.lambda_security_group_ids
  kms_key_arn        = module.foundation.kms_key_arn

  output_bucket_name    = module.application_core.output_bucket_name
  case_index_table_name = module.application_core.case_index_table_name
  case_index_table_arn  = module.application_core.case_index_table_arn
  case_embed_queue_url  = module.application_core.case_embed_queue_url

  portal_ui_bucket_name = var.portal_ui_bucket_name

  bedrock_analysis_model_id = var.bedrock_analysis_model_id
  bedrock_analysis_model_arn = var.bedrock_analysis_model_arn

  opensearch_endpoint    = module.foundation.opensearch_endpoint
  opensearch_domain_arn  = module.foundation.opensearch_domain_arn
  opensearch_case_index  = var.opensearch_case_index
  opensearch_soc_index   = var.opensearch_soc_index
  opensearch_splunk_index = var.opensearch_splunk_index
  rag_tenant_id          = var.rag_tenant_id

  portal_auth_mode            = "jwt"
  portal_jwt_issuer           = var.portal_jwt_issuer
  portal_jwt_audience         = var.portal_jwt_audience
  portal_jwt_tenant_id        = var.portal_jwt_tenant_id
  portal_required_analyst_role = var.portal_required_analyst_role
  portal_cors_allowed_origins = toset([var.portal_origin])

  tags = var.tags
}
```

For a scope-based identity provider, set `portal_required_analyst_scope` instead of `portal_required_analyst_role`. JWT mode refuses to plan unless issuer, audience, and at least one of those application authorization claims are set. Health, readiness, and static SPA routes stay public; only `/api` and `/api/{proxy+}` are protected.

Set `chat_history_enabled = true` only when persisted chat history is required. The default matches the existing customer-default deployment and does not create the two chat tables.

## OpenSearch and KMS policy wiring

The role name is always `${name_prefix}-portal-api-role`. Use `portal_lambda_role_arn` in the OpenSearch read-role allowlist and, when using a customer KMS key, in the key policy. The root module can calculate this ARN before apply because the name is deterministic.

The VPC network-interface actions use `Resource = "*"` because the EC2 API does not support resource-level permissions for all Lambda ENI operations. All data-plane permissions are scoped to the exact table, bucket paths, Bedrock models, OpenSearch domain, KMS key, and log group.

## Validate

```bash
terraform fmt -check -recursive deploy/terraform/application_portal
terraform -chdir=deploy/terraform/customer_default init
terraform -chdir=deploy/terraform/customer_default validate
terraform -chdir=deploy/terraform/customer_default plan
```

Live AWS validation is still required for the customer IdP issuer, VPC endpoint/DNS reachability, Bedrock model access, OpenSearch domain access policy, KMS key policy, and portal UI upload.
