locals {
  subnet_ids = var.enable_network ? module.network[0].subnet_ids : sort(var.private_subnet_ids)
  lambda_security_group_ids = var.enable_network ? toset(module.network[0].lambda_security_group_ids) : toset(
    var.existing_lambda_security_group_ids
  )
  kms_key_arn = var.enable_kms ? module.kms[0].kms_key_arn : var.existing_kms_key_arn
  vpc_id      = var.vpc_id
}

module "kms" {
  count  = var.enable_kms ? 1 : 0
  source = "../kms"

  aws_account_id       = var.aws_account_id
  aws_region           = var.aws_region
  key_alias            = var.kms_key_alias
  admin_principal_arns = var.kms_admin_principal_arns
  lambda_role_arns     = var.kms_lambda_role_arns
  enable_opensearch_grant = var.enable_opensearch
  tags                 = var.tags
}

module "network" {
  count  = var.enable_network ? 1 : 0
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
  count  = var.enable_ecr ? 1 : 0
  source = "../ecr"

  aws_account_id   = var.aws_account_id
  aws_region       = var.aws_region
  repository_name  = var.ecr_repository_name
  tags             = var.tags
}

module "opensearch" {
  count  = var.enable_opensearch ? 1 : 0
  source = "../opensearch"

  aws_account_id            = var.aws_account_id
  aws_region                = var.aws_region
  domain_name               = var.domain_name
  vpc_id                    = local.vpc_id
  subnet_ids                = toset(local.subnet_ids)
  lambda_security_group_ids = local.lambda_security_group_ids
  admin_principal_arns      = var.opensearch_admin_principal_arns
  read_role_arns            = var.read_role_arns
  write_role_arns           = var.write_role_arns
  engine_version            = var.engine_version
  instance_type             = var.instance_type
  instance_count            = var.instance_count
  volume_size_gib           = var.volume_size_gib
  kms_key_arn               = local.kms_key_arn
  tags                      = var.tags
}

resource "terraform_data" "foundation_preconditions" {
  lifecycle {
    precondition {
      condition     = !var.enable_network || var.vpc_id != ""
      error_message = "vpc_id is required when enable_network=true."
    }

    precondition {
      condition     = !var.enable_network || length(var.private_subnet_ids) >= 1
      error_message = "private_subnet_ids is required when enable_network=true."
    }

    precondition {
      condition = !var.enable_opensearch || (
        length(local.subnet_ids) >= 1 && length(local.lambda_security_group_ids) >= 1
      )
      error_message = "OpenSearch requires subnet IDs and Lambda security group IDs from network module or existing_* inputs."
    }

    precondition {
      condition     = !var.enable_kms || length(var.kms_admin_principal_arns) >= 1
      error_message = "kms_admin_principal_arns is required when enable_kms=true."
    }

    precondition {
      condition     = !var.enable_opensearch || length(var.opensearch_admin_principal_arns) >= 1
      error_message = "opensearch_admin_principal_arns is required when enable_opensearch=true."
    }

    precondition {
      condition     = var.vpc_id != "" || (!var.enable_network && !var.enable_opensearch)
      error_message = "vpc_id is required when network or OpenSearch modules are enabled."
    }
  }
}
