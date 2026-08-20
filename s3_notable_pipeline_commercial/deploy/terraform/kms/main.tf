data "aws_iam_policy_document" "key_policy" {
  statement {
    sid       = "AllowKeyAdministration"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = sort(tolist(var.admin_principal_arns))
    }
  }

  dynamic "statement" {
    for_each = var.enable_opensearch_grant ? [1] : []
    content {
      sid    = "AllowOpenSearchService"
      effect = "Allow"
      actions = [
        "kms:CreateGrant",
        "kms:Decrypt",
        "kms:DescribeKey",
      ]
      resources = ["*"]

      principals {
        type        = "Service"
        identifiers = ["es.amazonaws.com"]
      }

      condition {
        test     = "StringEquals"
        variable = "kms:ViaService"
        values   = ["es.${var.aws_region}.amazonaws.com"]
      }
    }
  }

  dynamic "statement" {
    for_each = length(var.lambda_role_arns) > 0 ? [1] : []
    content {
      sid    = "AllowProductLambdaUse"
      effect = "Allow"
      actions = [
        "kms:Decrypt",
        "kms:DescribeKey",
        "kms:GenerateDataKey",
      ]
      resources = ["*"]

      principals {
        type        = "AWS"
        identifiers = sort(tolist(var.lambda_role_arns))
      }
    }
  }
}

resource "aws_kms_key" "this" {
  description             = var.key_description
  deletion_window_in_days = var.deletion_window_in_days
  enable_key_rotation     = var.enable_key_rotation
  policy                  = data.aws_iam_policy_document.key_policy.json

  tags = {
    Name = var.key_alias
  }

  lifecycle {
    precondition {
      condition     = data.aws_partition.current.partition == "aws"
      error_message = "The commercial KMS stack must run in partition aws."
    }

    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "The commercial KMS stack must run in us-east-1."
    }

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Active AWS account does not match aws_account_id."
    }

    precondition {
      condition = alltrue([
        for arn in setunion(var.admin_principal_arns, var.lambda_role_arns) :
        split(":", arn)[4] == var.aws_account_id
      ])
      error_message = "All key policy principals must belong to aws_account_id."
    }
  }
}

resource "aws_kms_alias" "this" {
  name          = var.key_alias
  target_key_id = aws_kms_key.this.key_id
}
