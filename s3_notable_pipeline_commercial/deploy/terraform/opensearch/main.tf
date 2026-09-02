locals {
  domain_arn      = "arn:${data.aws_partition.current.partition}:es:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:domain/${var.domain_name}"
  domain_data_arn = "${local.domain_arn}/*"
  subnet_azs      = toset([for subnet in data.aws_subnet.selected : subnet.availability_zone])
}

data "aws_subnet" "selected" {
  for_each = var.subnet_ids
  id       = each.value
}

data "aws_security_group" "lambda" {
  for_each = var.lambda_security_group_ids
  id       = each.value
}

data "aws_iam_policy_document" "domain_access" {
  statement {
    sid       = "AllowApprovedAdministrators"
    effect    = "Allow"
    actions   = ["es:*"]
    resources = [local.domain_data_arn]

    principals {
      type        = "AWS"
      identifiers = sort(tolist(var.admin_principal_arns))
    }
  }

  dynamic "statement" {
    for_each = length(var.read_role_arns) > 0 ? [1] : []
    content {
      sid       = "AllowProductReadRoles"
      effect    = "Allow"
      actions   = ["es:ESHttpGet", "es:ESHttpPost"]
      resources = [local.domain_data_arn]

      principals {
        type        = "AWS"
        identifiers = ["arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"]
      }

      condition {
        test     = "ArnEquals"
        variable = "aws:PrincipalArn"
        values   = sort(tolist(var.read_role_arns))
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.write_role_arns) > 0 ? [1] : []
    content {
      sid    = "AllowProductWriteRoles"
      effect = "Allow"
      actions = [
        "es:ESHttpDelete",
        "es:ESHttpGet",
        "es:ESHttpPost",
        "es:ESHttpPut",
      ]
      resources = [local.domain_data_arn]

      principals {
        type        = "AWS"
        identifiers = ["arn:${data.aws_partition.current.partition}:iam::${var.aws_account_id}:root"]
      }

      condition {
        test     = "ArnEquals"
        variable = "aws:PrincipalArn"
        values   = sort(tolist(var.write_role_arns))
      }
    }
  }
}

resource "aws_iam_service_linked_role" "opensearch" {
  count            = var.create_service_linked_role ? 1 : 0
  aws_service_name = "opensearchservice.amazonaws.com"
  description      = "Allows Amazon OpenSearch Service to manage VPC resources."
}

resource "aws_security_group" "opensearch" {
  name_prefix = "${var.domain_name}-"
  description = "VPC-only HTTPS access to ${var.domain_name} from product Lambda security groups"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.domain_name}-opensearch"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "lambda_https" {
  for_each = var.lambda_security_group_ids

  security_group_id            = aws_security_group.opensearch.id
  referenced_security_group_id = each.value
  description                  = "HTTPS from product Lambda security group ${each.value}"
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_opensearch_domain" "this" {
  domain_name     = var.domain_name
  engine_version  = var.engine_version
  access_policies = data.aws_iam_policy_document.domain_access.json

  cluster_config {
    instance_type            = var.instance_type
    instance_count           = var.instance_count
    zone_awareness_enabled   = length(var.subnet_ids) > 1
    dedicated_master_enabled = var.dedicated_master_enabled
    dedicated_master_type    = var.dedicated_master_enabled ? var.dedicated_master_type : null
    dedicated_master_count   = var.dedicated_master_enabled ? var.dedicated_master_count : null

    dynamic "zone_awareness_config" {
      for_each = length(var.subnet_ids) > 1 ? [1] : []
      content {
        availability_zone_count = length(var.subnet_ids)
      }
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = var.volume_size_gib
  }

  vpc_options {
    subnet_ids         = sort(tolist(var.subnet_ids))
    security_group_ids = [aws_security_group.opensearch.id]
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = var.kms_key_arn
  }

  node_to_node_encryption {
    enabled = true
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  snapshot_options {
    automated_snapshot_start_hour = var.automated_snapshot_start_hour
  }

  software_update_options {
    auto_software_update_enabled = true
  }

  advanced_options = {
    "rest.action.multi.allow_explicit_index" = "true"
  }

  tags = {
    Name = var.domain_name
  }

  depends_on = [
    aws_iam_service_linked_role.opensearch,
    aws_vpc_security_group_ingress_rule.lambda_https,
  ]

  lifecycle {
    precondition {
      condition     = data.aws_partition.current.partition == "aws"
      error_message = "The commercial OpenSearch stack must run in partition aws."
    }

    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "The commercial OpenSearch stack must run in us-east-1."
    }

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Active AWS account does not match aws_account_id."
    }

    precondition {
      condition     = alltrue([for subnet in data.aws_subnet.selected : subnet.vpc_id == var.vpc_id])
      error_message = "Every subnet must belong to vpc_id."
    }

    precondition {
      condition     = length(local.subnet_azs) == length(var.subnet_ids)
      error_message = "Provide no more than one OpenSearch subnet per Availability Zone."
    }

    precondition {
      condition     = alltrue([for group in data.aws_security_group.lambda : group.vpc_id == var.vpc_id])
      error_message = "Every Lambda security group must belong to vpc_id."
    }

    precondition {
      condition     = var.instance_count % length(var.subnet_ids) == 0
      error_message = "instance_count must divide evenly across the selected Availability Zones."
    }

    precondition {
      condition     = length(setintersection(var.read_role_arns, var.write_role_arns)) == 0
      error_message = "Put each Lambda role in either read_role_arns or write_role_arns, not both."
    }

    precondition {
      condition = alltrue([
        for arn in setunion(var.admin_principal_arns, var.read_role_arns, var.write_role_arns) :
        split(":", arn)[4] == var.aws_account_id
      ])
      error_message = "All domain access principals must belong to aws_account_id."
    }

    precondition {
      condition     = var.kms_key_arn == null || split(":", var.kms_key_arn)[4] == var.aws_account_id
      error_message = "kms_key_arn must belong to aws_account_id."
    }
  }

  timeouts {
    create = "90m"
    update = "180m"
    delete = "90m"
  }
}
