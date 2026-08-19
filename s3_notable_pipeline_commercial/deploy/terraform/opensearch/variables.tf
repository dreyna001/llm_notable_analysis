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

variable "domain_name" {
  description = "OpenSearch domain name, unique within the AWS account and region."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,27}$", var.domain_name))
    error_message = "domain_name must be 3-28 lowercase characters, start with a letter, and contain only letters, digits, or hyphens."
  }
}

variable "vpc_id" {
  description = "Existing customer VPC ID."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-f]+$", var.vpc_id))
    error_message = "vpc_id must be a valid VPC ID."
  }
}

variable "subnet_ids" {
  description = "One private subnet per Availability Zone; one subnet is allowed for development, two or three for production."
  type        = set(string)

  validation {
    condition = (
      length(var.subnet_ids) >= 1 &&
      length(var.subnet_ids) <= 3 &&
      alltrue([for id in var.subnet_ids : can(regex("^subnet-[0-9a-f]+$", id))])
    )
    error_message = "subnet_ids must contain one to three valid subnet IDs."
  }
}

variable "lambda_security_group_ids" {
  description = "Existing Lambda security groups allowed to reach the domain over HTTPS."
  type        = set(string)

  validation {
    condition = (
      length(var.lambda_security_group_ids) >= 1 &&
      alltrue([for id in var.lambda_security_group_ids : can(regex("^sg-[0-9a-f]+$", id))])
    )
    error_message = "lambda_security_group_ids must contain at least one valid security group ID."
  }
}

variable "admin_principal_arns" {
  description = "Approved deployment or break-glass IAM role ARNs used during Phase A administration."
  type        = set(string)

  validation {
    condition = (
      length(var.admin_principal_arns) >= 1 &&
      alltrue([for arn in var.admin_principal_arns : can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", arn))])
    )
    error_message = "admin_principal_arns must contain at least one commercial AWS IAM role ARN."
  }
}

variable "read_role_arns" {
  description = "Phase B Lambda role ARNs allowed to perform signed read/search requests."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.read_role_arns : can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", arn))])
    error_message = "read_role_arns must contain only commercial AWS IAM role ARNs."
  }
}

variable "write_role_arns" {
  description = "Phase B ingestion and case-embed Lambda role ARNs allowed to manage index documents."
  type        = set(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.write_role_arns : can(regex("^arn:aws:iam::[0-9]{12}:role/.+$", arn))])
    error_message = "write_role_arns must contain only commercial AWS IAM role ARNs."
  }
}

variable "engine_version" {
  description = "Customer-approved OpenSearch 2.x engine version."
  type        = string
  default     = "OpenSearch_2.11"

  validation {
    condition     = can(regex("^OpenSearch_2\\.[0-9]+$", var.engine_version))
    error_message = "engine_version must be an OpenSearch 2.x identifier such as OpenSearch_2.11."
  }
}

variable "instance_type" {
  description = "OpenSearch data-node instance type."
  type        = string
  default     = "t3.small.search"
}

variable "instance_count" {
  description = "Number of OpenSearch data nodes. Must divide evenly across selected subnets/AZs."
  type        = number
  default     = 2

  validation {
    condition     = var.instance_count >= 1
    error_message = "instance_count must be at least 1."
  }
}

variable "dedicated_master_enabled" {
  description = "Enable dedicated cluster-manager nodes for a production-sized domain."
  type        = bool
  default     = false
}

variable "dedicated_master_type" {
  description = "Dedicated cluster-manager node instance type when enabled."
  type        = string
  default     = "m6g.large.search"
}

variable "dedicated_master_count" {
  description = "Dedicated cluster-manager node count when enabled."
  type        = number
  default     = 3

  validation {
    condition     = contains([3, 5], var.dedicated_master_count)
    error_message = "dedicated_master_count must be 3 or 5."
  }
}

variable "volume_size_gib" {
  description = "gp3 EBS volume size per data node in GiB."
  type        = number
  default     = 50

  validation {
    condition     = var.volume_size_gib >= 10
    error_message = "volume_size_gib must be at least 10 GiB."
  }
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key ARN. Null uses the AWS-managed OpenSearch key."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.kms_key_arn == null ||
      can(regex("^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]+$", var.kms_key_arn))
    )
    error_message = "kms_key_arn must be null or a us-east-1 commercial AWS KMS key ARN."
  }
}

variable "create_service_linked_role" {
  description = "Create the OpenSearch service-linked role. Enable only when the account does not already have it."
  type        = bool
  default     = false
}

variable "automated_snapshot_start_hour" {
  description = "UTC hour for the daily automated snapshot window."
  type        = number
  default     = 3

  validation {
    condition     = var.automated_snapshot_start_hour >= 0 && var.automated_snapshot_start_hour <= 23
    error_message = "automated_snapshot_start_hour must be between 0 and 23."
  }
}

variable "tags" {
  description = "Additional customer tags applied through the AWS provider."
  type        = map(string)
  default     = {}
}
