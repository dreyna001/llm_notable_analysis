locals {
  role_arns = {
    analyzer      = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.name_prefix}-analyzer-role"
    case_embed    = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.name_prefix}-case-embed-role"
    rag_ingestion = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.name_prefix}-rag-ingestion-role"
    portal        = "arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:role/${var.name_prefix}-portal-api-role"
  }

  ecr_repository_uri  = var.create_ecr_repository ? module.ecr[0].ecr_repository_uri : var.existing_ecr_repository_uri
  image_uri           = "${local.ecr_repository_uri}@${var.image_digest}"
  kms_key_arn         = var.create_kms_key ? module.kms[0].kms_key_arn : (var.existing_kms_key_arn == "" ? null : var.existing_kms_key_arn)
  opensearch_endpoint = var.create_opensearch_domain ? module.opensearch[0].opensearch_endpoint : var.existing_opensearch_endpoint
  opensearch_arn      = var.create_opensearch_domain ? module.opensearch[0].opensearch_domain_arn : var.existing_opensearch_domain_arn
  lambda_security_group_ids = distinct(concat(
    module.network.lambda_security_group_ids,
    var.lambda_security_group_ids,
  ))
}

resource "terraform_data" "deployment_contract" {
  lifecycle {
    precondition {
      condition     = data.aws_partition.current.partition == "aws"
      error_message = "The customer-default stack supports the commercial aws partition only."
    }
    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "The customer-default stack supports us-east-1 only."
    }
    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Active AWS account does not match aws_account_id."
    }
    precondition {
      condition     = length(var.private_subnet_ids) >= 1 && length(var.private_subnet_ids) <= 3
      error_message = "private_subnet_ids must contain one to three subnets."
    }
    precondition {
      condition     = length(local.lambda_security_group_ids) >= 1
      error_message = "At least one Lambda security group is required."
    }
    precondition {
      condition     = !var.deploy_application || can(regex("^sha256:[a-f0-9]{64}$", var.image_digest))
      error_message = "Set image_digest to an immutable sha256 digest before the full plan."
    }
    precondition {
      condition     = var.create_ecr_repository || can(regex("^[0-9]{12}\\.dkr\\.ecr\\.us-east-1\\.amazonaws\\.com/.+$", var.existing_ecr_repository_uri))
      error_message = "Set an existing us-east-1 ECR repository URI when create_ecr_repository is false."
    }
    precondition {
      condition     = !var.deploy_application || var.create_opensearch_domain || (startswith(var.existing_opensearch_endpoint, "https://") && var.existing_opensearch_domain_arn != "")
      error_message = "Supply the existing OpenSearch endpoint and ARN when Terraform does not create the domain."
    }
    precondition {
      condition     = !var.create_kms_key || length(var.admin_principal_arns) > 0
      error_message = "A Terraform-managed KMS key requires at least one administrator role ARN."
    }
    precondition {
      condition     = var.existing_kms_key_arn == "" || var.existing_kms_policy_ready
      error_message = "Set existing_kms_policy_ready only after applying the documented Path B grants to the existing key."
    }
    precondition {
      condition     = var.create_opensearch_domain || var.replace_existing_opensearch_access_policy
      error_message = "Existing-domain mode replaces its complete access policy; explicit replacement approval is required."
    }
    precondition {
      condition     = !var.deploy_application || (var.portal_jwt_issuer != "" && var.portal_jwt_audience != "" && (var.portal_required_analyst_role != "" || var.portal_required_analyst_scope != ""))
      error_message = "JWT deployment requires issuer, audience, and an analyst role or scope."
    }
  }
}

module "network" {
  source = "../network"

  aws_account_id                            = var.aws_account_id
  aws_region                                = var.aws_region
  vpc_id                                    = var.vpc_id
  private_subnet_ids                        = var.private_subnet_ids
  name_prefix                               = var.name_prefix
  create_s3_gateway_endpoint                = var.create_s3_gateway_endpoint
  create_dynamodb_gateway_endpoint          = var.create_dynamodb_gateway_endpoint
  create_sqs_interface_endpoint             = var.create_sqs_interface_endpoint
  create_logs_interface_endpoint            = var.create_logs_interface_endpoint
  create_bedrock_runtime_interface_endpoint = var.create_bedrock_runtime_interface_endpoint
  create_secretsmanager_interface_endpoint  = var.create_secretsmanager_interface_endpoint
  tags                                      = var.tags
}

module "ecr" {
  count  = var.create_ecr_repository ? 1 : 0
  source = "../ecr"

  aws_account_id  = var.aws_account_id
  aws_region      = var.aws_region
  repository_name = var.ecr_repository_name
  tags            = var.tags
}

module "kms" {
  count  = var.create_kms_key ? 1 : 0
  source = "../kms"

  aws_account_id       = var.aws_account_id
  aws_region           = var.aws_region
  key_alias            = var.kms_key_alias
  admin_principal_arns = var.admin_principal_arns
  lambda_role_arns     = toset(values(local.role_arns))
  s3_notification_bucket_arns = toset([
    "arn:${data.aws_partition.current.partition}:s3:::${var.input_bucket_name}",
  ])
  tags = var.tags
}

module "opensearch" {
  count  = var.create_opensearch_domain ? 1 : 0
  source = "../opensearch"

  aws_account_id             = var.aws_account_id
  aws_region                 = var.aws_region
  domain_name                = var.opensearch_domain_name
  vpc_id                     = var.vpc_id
  subnet_ids                 = toset(var.private_subnet_ids)
  lambda_security_group_ids  = toset(local.lambda_security_group_ids)
  admin_principal_arns       = var.admin_principal_arns
  read_role_arns             = toset([local.role_arns.analyzer, local.role_arns.portal])
  write_role_arns            = toset([local.role_arns.case_embed, local.role_arns.rag_ingestion])
  engine_version             = var.opensearch_engine_version
  instance_type              = var.opensearch_instance_type
  instance_count             = var.opensearch_instance_count
  volume_size_gib            = var.opensearch_volume_size_gib
  kms_key_arn                = local.kms_key_arn
  create_service_linked_role = var.create_opensearch_service_linked_role
  tags                       = var.tags
}

data "aws_iam_policy_document" "existing_opensearch" {
  count = var.deploy_application && !var.create_opensearch_domain ? 1 : 0

  statement {
    sid       = "AllowApprovedAdministrators"
    actions   = ["es:*"]
    resources = ["${var.existing_opensearch_domain_arn}/*"]
    principals {
      type        = "AWS"
      identifiers = sort(tolist(var.admin_principal_arns))
    }
  }
  statement {
    sid       = "AllowProductReadRoles"
    actions   = ["es:ESHttpGet", "es:ESHttpPost"]
    resources = ["${var.existing_opensearch_domain_arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.role_arns.analyzer, local.role_arns.portal]
    }
  }
  statement {
    sid       = "AllowProductWriteRoles"
    actions   = ["es:ESHttpDelete", "es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut"]
    resources = ["${var.existing_opensearch_domain_arn}/*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:PrincipalArn"
      values   = [local.role_arns.case_embed, local.role_arns.rag_ingestion]
    }
  }
}

resource "aws_opensearch_domain_policy" "existing" {
  count = var.deploy_application && !var.create_opensearch_domain ? 1 : 0

  domain_name     = reverse(split("/", var.existing_opensearch_domain_arn))[0]
  access_policies = data.aws_iam_policy_document.existing_opensearch[0].json
}

module "application_core" {
  count  = var.deploy_application ? 1 : 0
  source = "../application_core"

  name_prefix                          = var.name_prefix
  image_uri                            = local.image_uri
  input_bucket_name                    = var.input_bucket_name
  output_bucket_name                   = var.output_bucket_name
  kms_key_arn                          = local.kms_key_arn
  subnet_ids                           = var.private_subnet_ids
  security_group_ids                   = local.lambda_security_group_ids
  bedrock_analysis_model_id            = var.bedrock_analysis_model_id
  bedrock_analysis_model_arn           = var.bedrock_analysis_model_arn
  bedrock_inference_profile_model_arns = tolist(var.bedrock_analysis_inference_profile_foundation_model_arns)
  opensearch_endpoint                  = local.opensearch_endpoint
  opensearch_domain_arn                = local.opensearch_arn
  rag_tenant_id                        = var.rag_tenant_id
  opensearch_indexes = {
    case_chunks       = var.opensearch_case_index
    soc_knowledge     = var.opensearch_soc_index
    splunk_dictionary = var.opensearch_splunk_index
  }
  case_index_table_name        = var.case_index_table_name
  alarm_notification_topic_arn = var.alarm_notification_topic_arn
  tags                         = var.tags
}

module "application_portal" {
  count  = var.deploy_application ? 1 : 0
  source = "../application_portal"

  aws_account_id                                           = var.aws_account_id
  aws_region                                               = var.aws_region
  name_prefix                                              = var.name_prefix
  image_uri                                                = local.image_uri
  tags                                                     = var.tags
  subnet_ids                                               = var.private_subnet_ids
  security_group_ids                                       = local.lambda_security_group_ids
  kms_key_arn                                              = local.kms_key_arn
  output_bucket_name                                       = module.application_core[0].output_bucket_name
  portal_ui_bucket_name                                    = var.portal_ui_bucket_name
  case_index_table_name                                    = module.application_core[0].case_index_table_name
  case_index_table_arn                                     = module.application_core[0].case_index_table_arn
  case_embed_queue_url                                     = module.application_core[0].case_embed_queue_url
  bedrock_analysis_model_id                                = var.bedrock_analysis_model_id
  bedrock_analysis_model_arn                               = var.bedrock_analysis_model_arn
  bedrock_analysis_inference_profile_foundation_model_arns = var.bedrock_analysis_inference_profile_foundation_model_arns
  opensearch_endpoint                                      = local.opensearch_endpoint
  opensearch_domain_arn                                    = local.opensearch_arn
  opensearch_case_index                                    = var.opensearch_case_index
  opensearch_soc_index                                     = var.opensearch_soc_index
  opensearch_splunk_index                                  = var.opensearch_splunk_index
  rag_tenant_id                                            = var.rag_tenant_id
  portal_auth_mode                                         = "jwt"
  portal_jwt_issuer                                        = var.portal_jwt_issuer
  portal_jwt_audience                                      = var.portal_jwt_audience
  portal_jwt_tenant_id                                     = var.portal_jwt_tenant_id
  portal_required_analyst_role                             = var.portal_required_analyst_role
  portal_required_analyst_scope                            = var.portal_required_analyst_scope
  portal_cors_allowed_origins                              = var.portal_cors_allowed_origins
  alarm_notification_topic_arns                            = var.alarm_notification_topic_arn == null ? [] : [var.alarm_notification_topic_arn]
}
