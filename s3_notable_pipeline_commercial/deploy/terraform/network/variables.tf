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

variable "vpc_id" {
  description = "Existing customer VPC ID."
  type        = string

  validation {
    condition     = can(regex("^vpc-[0-9a-f]+$", var.vpc_id))
    error_message = "vpc_id must be a valid VPC ID."
  }
}

variable "private_subnet_ids" {
  description = "Existing private subnet IDs for Lambda ENIs and optional interface endpoints; one to three subnets, one per Availability Zone."
  type        = list(string)

  validation {
    condition = (
      length(var.private_subnet_ids) >= 1 &&
      length(var.private_subnet_ids) <= 3 &&
      alltrue([for id in var.private_subnet_ids : can(regex("^subnet-[0-9a-f]+$", id))]) &&
      length(distinct(var.private_subnet_ids)) == length(var.private_subnet_ids)
    )
    error_message = "private_subnet_ids must contain one to three unique valid subnet IDs."
  }
}

variable "name_prefix" {
  description = "Optional prefix for created security groups and VPC endpoint Name tags."
  type        = string
  default     = "notable-analyzer"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{0,62}$", var.name_prefix))
    error_message = "name_prefix must start with a lowercase letter and contain only lowercase letters, digits, or hyphens."
  }
}

variable "create_s3_gateway_endpoint" {
  description = "Create an S3 gateway VPC endpoint and associate it with private subnet route tables."
  type        = bool
  default     = false
}

variable "create_dynamodb_gateway_endpoint" {
  description = "Create a DynamoDB gateway VPC endpoint and associate it with private subnet route tables."
  type        = bool
  default     = false
}

variable "create_sqs_interface_endpoint" {
  description = "Create an SQS interface VPC endpoint in the private subnets."
  type        = bool
  default     = false
}

variable "create_logs_interface_endpoint" {
  description = "Create a CloudWatch Logs interface VPC endpoint in the private subnets."
  type        = bool
  default     = false
}

variable "create_bedrock_runtime_interface_endpoint" {
  description = "Create a Bedrock Runtime interface VPC endpoint in the private subnets."
  type        = bool
  default     = false
}

variable "create_secretsmanager_interface_endpoint" {
  description = "Create a Secrets Manager interface VPC endpoint in the private subnets."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional customer tags applied through the AWS provider."
  type        = map(string)
  default     = {}
}
