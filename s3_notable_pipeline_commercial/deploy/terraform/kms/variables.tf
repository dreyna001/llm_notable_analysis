variable "aws_account_id" {
  description = "Approved 12-digit commercial AWS account ID."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "Commercial AWS deployment region. This product supports us-east-1 only."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must be us-east-1 for the commercial product."
  }
}

variable "key_alias" {
  description = "KMS alias for the customer-managed key, including the alias/ prefix."
  type        = string

  validation {
    condition     = can(regex("^alias/[a-zA-Z0-9:/_-]+$", var.key_alias))
    error_message = "key_alias must start with alias/ and contain only valid KMS alias characters."
  }
}

variable "admin_principal_arns" {
  description = "Approved deployment or break-glass IAM role ARNs used during Phase A key administration."
  type        = set(string)

  validation {
    condition = (
      length(var.admin_principal_arns) >= 1 &&
      alltrue([for arn in var.admin_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", arn))])
    )
    error_message = "admin_principal_arns must contain at least one commercial AWS IAM role ARN."
  }
}

variable "lambda_role_arns" {
  description = "Phase B Lambda role ARNs allowed to decrypt, describe, and generate data keys."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.lambda_role_arns : can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", arn))])
    error_message = "lambda_role_arns must contain only commercial AWS IAM role ARNs."
  }
}

variable "s3_notification_bucket_arns" {
  description = "S3 bucket ARNs allowed to publish notifications to product queues encrypted by this key."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.s3_notification_bucket_arns : can(regex("^arn:aws:s3:::[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", arn))])
    error_message = "s3_notification_bucket_arns must contain valid commercial S3 bucket ARNs."
  }
}

variable "enable_opensearch_grant" {
  description = "Allow the OpenSearch service principal to use this key for domain encryption at rest."
  type        = bool
  default     = true
}

variable "enable_key_rotation" {
  description = "Enable automatic annual rotation for the customer-managed key."
  type        = bool
  default     = true
}

variable "key_description" {
  description = "Description applied to the customer-managed KMS key."
  type        = string
  default     = "notable-analyzer commercial data-plane encryption"
}

variable "deletion_window_in_days" {
  description = "Waiting period before scheduled key deletion."
  type        = number
  default     = 30

  validation {
    condition     = var.deletion_window_in_days >= 7 && var.deletion_window_in_days <= 30
    error_message = "deletion_window_in_days must be between 7 and 30."
  }
}

variable "tags" {
  description = "Additional customer tags applied through the AWS provider."
  type        = map(string)
  default     = {}
}
