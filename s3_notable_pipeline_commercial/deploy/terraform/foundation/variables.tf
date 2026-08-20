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

variable "tags" {
  description = "Optional tags applied to created resources."
  type        = map(string)
  default     = {}
}

variable "enable_kms" {
  description = "Create the customer-managed KMS key module."
  type        = bool
  default     = false
}

variable "enable_network" {
  description = "Create the Lambda security group and optional VPC endpoints module."
  type        = bool
  default     = true
}

variable "enable_ecr" {
  description = "Create the ECR repository module."
  type        = bool
  default     = true
}

variable "enable_opensearch" {
  description = "Create the OpenSearch domain module."
  type        = bool
  default     = true
}

variable "vpc_id" {
  description = "Existing customer VPC ID."
  type        = string
  default     = ""

  validation {
    condition     = var.vpc_id == "" || can(regex("^vpc-[0-9a-f]+$", var.vpc_id))
    error_message = "vpc_id must be empty or a valid VPC ID."
  }
}

variable "private_subnet_ids" {
  description = "Existing private subnet IDs for Lambda and OpenSearch."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for id in var.private_subnet_ids : can(regex("^subnet-[0-9a-f]+$", id))
    ])
    error_message = "private_subnet_ids must contain valid subnet IDs."
  }
}

variable "existing_lambda_security_group_ids" {
  description = "Use when enable_network=false."
  type        = list(string)
  default     = []
}

variable "existing_kms_key_arn" {
  description = "Use when enable_kms=false and OpenSearch or SAM need a CMK."
  type        = string
  default     = null
}

variable "name_prefix" {
  description = "Resource name prefix for network module."
  type        = string
  default     = "notable"
}

variable "create_s3_gateway_endpoint" {
  type    = bool
  default = false
}

variable "create_dynamodb_gateway_endpoint" {
  type    = bool
  default = false
}

variable "create_sqs_interface_endpoint" {
  type    = bool
  default = false
}

variable "create_logs_interface_endpoint" {
  type    = bool
  default = false
}

variable "create_bedrock_runtime_interface_endpoint" {
  type    = bool
  default = false
}

variable "create_secretsmanager_interface_endpoint" {
  type    = bool
  default = false
}

variable "kms_key_alias" {
  type    = string
  default = "alias/notable-analyzer"
}

variable "kms_admin_principal_arns" {
  type    = set(string)
  default = []
}

variable "kms_lambda_role_arns" {
  description = "Phase B Lambda role ARNs for the CMK key policy."
  type        = set(string)
  default     = []
}

variable "ecr_repository_name" {
  type    = string
  default = "notable-analyzer-s3"
}

variable "domain_name" {
  type    = string
  default = "notable-rag-staging"
}

variable "opensearch_admin_principal_arns" {
  type    = set(string)
  default = []
}

variable "read_role_arns" {
  type    = set(string)
  default = []
}

variable "write_role_arns" {
  type    = set(string)
  default = []
}

variable "engine_version" {
  type    = string
  default = "OpenSearch_2.11"
}

variable "instance_type" {
  type    = string
  default = "t3.small.search"
}

variable "instance_count" {
  type    = number
  default = 2
}

variable "volume_size_gib" {
  type    = number
  default = 50
}
