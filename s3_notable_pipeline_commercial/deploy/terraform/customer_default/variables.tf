variable "aws_account_id" {
  type        = string
  description = "Approved 12-digit commercial AWS account ID."
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "Supported commercial AWS region."
  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must be us-east-1."
  }
}

variable "name_prefix" {
  type        = string
  default     = "notable"
  description = "Deterministic resource-name prefix."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,26}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-28 lowercase letters, numbers, or hyphens."
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Customer tags added to managed resources."
}

variable "deploy_application" {
  type        = bool
  default     = true
  description = "Create the application after its immutable image is available. Set false only for ECR bootstrap."
}

variable "create_ecr_repository" {
  type        = bool
  default     = true
  description = "Create the application ECR repository."
}

variable "ecr_repository_name" {
  type        = string
  default     = "notable-analyzer-s3"
  description = "ECR repository name when Terraform creates it."
}

variable "existing_ecr_repository_uri" {
  type        = string
  default     = ""
  description = "Existing ECR repository URI, or the expected URI during a first ECR bootstrap."
}

variable "image_digest" {
  type        = string
  default     = ""
  description = "Immutable image digest in sha256:<64 lowercase hex> form."
}

variable "vpc_id" {
  type        = string
  description = "Existing customer VPC ID."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "One to three existing private subnet IDs, one per Availability Zone."
}

variable "lambda_security_group_ids" {
  type        = list(string)
  default     = []
  description = "Existing Lambda security groups with required private egress."
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

variable "create_kms_key" {
  type        = bool
  default     = false
  description = "Create and wire a customer-managed KMS key."
}

variable "existing_kms_key_arn" {
  type        = string
  default     = ""
  description = "Existing KMS key ARN; empty uses AWS-managed encryption when create_kms_key is false."
}

variable "existing_kms_policy_ready" {
  type        = bool
  default     = false
  description = "Explicit confirmation that an existing key policy permits all documented Path B service and role use."
}

variable "kms_key_alias" {
  type        = string
  default     = "alias/notable-customer-default"
  description = "Alias for a Terraform-managed KMS key."
}

variable "create_opensearch_domain" {
  type        = bool
  default     = true
  description = "Create the VPC-only OpenSearch domain."
}

variable "opensearch_domain_name" {
  type        = string
  default     = "notable-rag"
  description = "OpenSearch domain name when Terraform creates it."
}

variable "existing_opensearch_endpoint" {
  type        = string
  default     = ""
  description = "Existing VPC-only OpenSearch HTTPS endpoint."
}

variable "existing_opensearch_domain_arn" {
  type        = string
  default     = ""
  description = "Existing VPC-only OpenSearch domain ARN."
}

variable "replace_existing_opensearch_access_policy" {
  type        = bool
  default     = false
  description = "Explicit approval for Terraform to replace the complete access policy of a dedicated existing domain."
}

variable "admin_principal_arns" {
  type        = set(string)
  description = "Approved IAM administrator role ARNs for KMS and OpenSearch."
}

variable "create_opensearch_service_linked_role" {
  type        = bool
  default     = false
  description = "Create the OpenSearch service-linked role if the account does not have it."
}

variable "opensearch_engine_version" {
  type    = string
  default = "OpenSearch_2.11"
}
variable "opensearch_instance_type" {
  type    = string
  default = "t3.small.search"
}
variable "opensearch_instance_count" {
  type    = number
  default = 2
}
variable "opensearch_volume_size_gib" {
  type    = number
  default = 50
}

variable "bedrock_analysis_model_id" { type = string }
variable "bedrock_analysis_model_arn" { type = string }
variable "bedrock_analysis_inference_profile_foundation_model_arns" {
  type    = set(string)
  default = []
}

variable "input_bucket_name" { type = string }
variable "output_bucket_name" { type = string }
variable "case_index_table_name" {
  type    = string
  default = "notable-case-index"
}
variable "portal_ui_bucket_name" { type = string }

variable "portal_jwt_issuer" { type = string }
variable "portal_jwt_audience" { type = string }
variable "portal_jwt_tenant_id" {
  type    = string
  default = ""
}
variable "portal_required_analyst_role" {
  type    = string
  default = ""
}
variable "portal_required_analyst_scope" {
  type    = string
  default = ""
}
variable "portal_cors_allowed_origins" { type = set(string) }

variable "rag_tenant_id" { type = string }
variable "opensearch_soc_index" {
  type    = string
  default = "soc_knowledge"
}
variable "opensearch_splunk_index" {
  type    = string
  default = "splunk_dictionary"
}
variable "opensearch_case_index" {
  type    = string
  default = "case_chunks"
}

variable "alarm_notification_topic_arn" {
  type        = string
  default     = null
  nullable    = true
  description = "Optional SNS topic ARN for application alarms."
}
