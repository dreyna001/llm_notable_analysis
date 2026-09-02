variable "aws_account_id" {
  description = "Approved 12-digit commercial AWS account ID."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "Commercial AWS deployment region."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must be us-east-1 for the commercial product."
  }
}

variable "name_prefix" {
  description = "Prefix used for deterministic portal resource names."
  type        = string
  default     = "notable"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-32 lowercase letters, numbers, or hyphens, starting with a letter."
  }
}

variable "image_uri" {
  description = "Immutable us-east-1 ECR image URI including an sha256 digest."
  type        = string

  validation {
    condition = can(regex(
      "^[0-9]{12}\\.dkr\\.ecr\\.us-east-1\\.amazonaws\\.com/[A-Za-z0-9._/-]+@sha256:[a-f0-9]{64}$",
      var.image_uri,
    ))
    error_message = "image_uri must be a us-east-1 ECR URI pinned with @sha256:<64 lowercase hex characters>."
  }
}

variable "tags" {
  description = "Tags applied to portal resources."
  type        = map(string)
  default     = {}
}

variable "subnet_ids" {
  description = "Private subnet IDs for the portal Lambda. Leave empty only for a non-VPC deployment."
  type        = list(string)

  validation {
    condition     = alltrue([for id in var.subnet_ids : can(regex("^subnet-[0-9a-f]+$", id))])
    error_message = "subnet_ids must contain valid subnet IDs."
  }
}

variable "security_group_ids" {
  description = "Security group IDs for the portal Lambda. Leave empty only for a non-VPC deployment."
  type        = list(string)

  validation {
    condition     = alltrue([for id in var.security_group_ids : can(regex("^sg-[0-9a-f]+$", id))])
    error_message = "security_group_ids must contain valid security group IDs."
  }
}

variable "kms_key_arn" {
  description = "Optional customer KMS key used by the portal data stores, logs, S3, and Lambda environment."
  type        = string
  default     = null

  validation {
    condition = var.kms_key_arn == null || can(regex(
      "^arn:aws:kms:us-east-1:[0-9]{12}:key/[0-9a-f-]+$",
      var.kms_key_arn,
    ))
    error_message = "kms_key_arn must be null or a commercial us-east-1 KMS key ARN."
  }
}

variable "output_bucket_name" {
  description = "Existing application output bucket containing reports and case archives."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.output_bucket_name)) && !can(regex("\\.\\.", var.output_bucket_name))
    error_message = "output_bucket_name must be a valid S3 bucket name."
  }
}

variable "portal_ui_bucket_name" {
  description = "Private S3 bucket created for the analyst portal SPA."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.portal_ui_bucket_name)) && !can(regex("\\.\\.", var.portal_ui_bucket_name))
    error_message = "portal_ui_bucket_name must be a valid S3 bucket name."
  }
}

variable "case_index_table_name" {
  description = "DynamoDB CaseIndex table name created by the core application module."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,255}$", var.case_index_table_name))
    error_message = "case_index_table_name must be a valid DynamoDB table name."
  }
}

variable "case_index_table_arn" {
  description = "DynamoDB CaseIndex table ARN created by the core application module."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:dynamodb:us-east-1:[0-9]{12}:table/[A-Za-z0-9_.-]{3,255}$", var.case_index_table_arn))
    error_message = "case_index_table_arn must be a commercial us-east-1 DynamoDB table ARN."
  }
}

variable "case_embed_queue_url" {
  description = "Case embedding queue URL created by the core application module."
  type        = string

  validation {
    condition     = can(regex("^https://sqs\\.us-east-1\\.amazonaws\\.com/[0-9]{12}/[A-Za-z0-9_-]+$", var.case_embed_queue_url))
    error_message = "case_embed_queue_url must be a commercial us-east-1 SQS queue URL."
  }
}

variable "case_archive_prefix" {
  description = "S3 prefix containing canonical case envelopes."
  type        = string
  default     = "cases"

  validation {
    condition     = can(regex("^[A-Za-z0-9!_.*'()/-]+$", var.case_archive_prefix)) && !startswith(var.case_archive_prefix, "/") && !endswith(var.case_archive_prefix, "/")
    error_message = "case_archive_prefix must be a non-empty relative S3 prefix without leading or trailing slashes."
  }
}

variable "case_archive_chunks_prefix" {
  description = "S3 prefix containing embedded case chunks."
  type        = string
  default     = "case_chunks"

  validation {
    condition     = can(regex("^[A-Za-z0-9!_.*'()/-]+$", var.case_archive_chunks_prefix)) && !startswith(var.case_archive_chunks_prefix, "/") && !endswith(var.case_archive_chunks_prefix, "/")
    error_message = "case_archive_chunks_prefix must be a non-empty relative S3 prefix without leading or trailing slashes."
  }
}

variable "case_retention_days" {
  description = "Retention used by case and chat records."
  type        = number
  default     = 30

  validation {
    condition     = var.case_retention_days >= 1 && var.case_retention_days <= 3650
    error_message = "case_retention_days must be between 1 and 3650."
  }
}

variable "capability_profiles" {
  description = "Runtime capability profiles for the customer-default portal."
  type        = string
  default     = "core,rag,analyst_portal"

  validation {
    condition     = length(trimspace(var.capability_profiles)) > 0
    error_message = "capability_profiles cannot be empty."
  }
}

variable "bedrock_analysis_model_id" {
  description = "Customer-approved Bedrock analysis model or inference-profile ID."
  type        = string

  validation {
    condition     = length(trimspace(var.bedrock_analysis_model_id)) > 0
    error_message = "bedrock_analysis_model_id cannot be empty."
  }
}

variable "bedrock_analysis_model_arn" {
  description = "Exact ARN corresponding to bedrock_analysis_model_id."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:bedrock:us-east-1:([0-9]{12})?:(foundation-model|inference-profile)/.+$", var.bedrock_analysis_model_arn))
    error_message = "bedrock_analysis_model_arn must be a supported commercial us-east-1 Bedrock model ARN."
  }
}

variable "bedrock_analysis_inference_profile_foundation_model_arns" {
  description = "Foundation-model ARNs permitted through the analysis inference profile."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.bedrock_analysis_inference_profile_foundation_model_arns :
      can(regex("^arn:aws:bedrock:[a-z0-9-]+::foundation-model/[A-Za-z0-9._:-]+$", arn))
    ])
    error_message = "Every analysis foundation model ARN must be a valid commercial Bedrock foundation-model ARN."
  }
}

variable "portal_chat_model_id" {
  description = "Optional Bedrock model override for portal answer synthesis."
  type        = string
  default     = ""
}

variable "portal_chat_model_arn" {
  description = "Exact Bedrock ARN for portal_chat_model_id."
  type        = string
  default     = ""

  validation {
    condition     = var.portal_chat_model_arn == "" || can(regex("^arn:aws:bedrock:us-east-1:([0-9]{12})?:(foundation-model|inference-profile)/.+$", var.portal_chat_model_arn))
    error_message = "portal_chat_model_arn must be empty or a supported commercial us-east-1 Bedrock model ARN."
  }
}

variable "portal_chat_inference_profile_foundation_model_arns" {
  description = "Foundation-model ARNs permitted through the portal chat inference profile."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.portal_chat_inference_profile_foundation_model_arns :
      can(regex("^arn:aws:bedrock:[a-z0-9-]+::foundation-model/[A-Za-z0-9._:-]+$", arn))
    ])
    error_message = "Every portal chat foundation model ARN must be a valid Bedrock foundation-model ARN."
  }
}

variable "portal_chat_vision_model_id" {
  description = "Optional Bedrock vision model override for portal chat images."
  type        = string
  default     = ""
}

variable "portal_chat_vision_model_arn" {
  description = "Exact Bedrock ARN for portal_chat_vision_model_id."
  type        = string
  default     = ""

  validation {
    condition     = var.portal_chat_vision_model_arn == "" || can(regex("^arn:aws:bedrock:us-east-1:([0-9]{12})?:(foundation-model|inference-profile)/.+$", var.portal_chat_vision_model_arn))
    error_message = "portal_chat_vision_model_arn must be empty or a supported commercial us-east-1 Bedrock model ARN."
  }
}

variable "portal_chat_vision_inference_profile_foundation_model_arns" {
  description = "Foundation-model ARNs permitted through the vision inference profile."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.portal_chat_vision_inference_profile_foundation_model_arns :
      can(regex("^arn:aws:bedrock:[a-z0-9-]+::foundation-model/[A-Za-z0-9._:-]+$", arn))
    ])
    error_message = "Every portal vision foundation model ARN must be a valid Bedrock foundation-model ARN."
  }
}

variable "case_qa_embedding_model" {
  description = "Bedrock embedding model used for Case Q&A retrieval."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"

  validation {
    condition     = var.case_qa_embedding_model == "amazon.titan-embed-text-v2:0"
    error_message = "case_qa_embedding_model is locked to amazon.titan-embed-text-v2:0 for the 1024-dimensional v1 index."
  }
}

variable "opensearch_endpoint" {
  description = "HTTPS endpoint of the private OpenSearch domain, without a trailing slash."
  type        = string

  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+$", var.opensearch_endpoint))
    error_message = "opensearch_endpoint must be an HTTPS host without a path or trailing slash."
  }
}

variable "opensearch_domain_arn" {
  description = "OpenSearch domain ARN used for least-privilege data-plane IAM."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:es:us-east-1:[0-9]{12}:domain/[a-z0-9-]+$", var.opensearch_domain_arn))
    error_message = "opensearch_domain_arn must be a commercial us-east-1 domain ARN."
  }
}

variable "opensearch_case_index" {
  type    = string
  default = "case_chunks"
}

variable "opensearch_soc_index" {
  type    = string
  default = "soc_knowledge"
}

variable "opensearch_splunk_index" {
  type    = string
  default = "splunk_dictionary"
}

variable "rag_tenant_id" {
  description = "Stable customer deployment or tenant identifier applied to OpenSearch queries."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$", var.rag_tenant_id))
    error_message = "rag_tenant_id must be 1-128 safe identifier characters."
  }
}

variable "portal_auth_mode" {
  description = "API Gateway authorization mode for protected portal routes."
  type        = string
  default     = "jwt"

  validation {
    condition     = contains(["jwt", "iam"], var.portal_auth_mode)
    error_message = "portal_auth_mode must be jwt or iam."
  }
}

variable "portal_jwt_issuer" {
  description = "OIDC JWT issuer. Required for JWT authentication."
  type        = string
  default     = ""

  validation {
    condition     = var.portal_jwt_issuer == "" || can(regex("^https://[^?# ]+$", var.portal_jwt_issuer))
    error_message = "portal_jwt_issuer must be an HTTPS URL."
  }
}

variable "portal_jwt_audience" {
  description = "JWT audience required for the portal API."
  type        = string
  default     = ""
}

variable "portal_jwt_tenant_id" {
  description = "Optional Entra tenant ID enforced by the portal application."
  type        = string
  default     = ""

  validation {
    condition     = var.portal_jwt_tenant_id == "" || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.portal_jwt_tenant_id))
    error_message = "portal_jwt_tenant_id must be empty or a UUID."
  }
}

variable "portal_required_analyst_role" {
  description = "Required analyst role claim value. Set this or portal_required_analyst_scope for JWT mode."
  type        = string
  default     = ""
}

variable "portal_required_analyst_scope" {
  description = "Required analyst scope claim value. Set this or portal_required_analyst_role for JWT mode."
  type        = string
  default     = ""
}

variable "portal_cors_allowed_origins" {
  description = "Exact HTTPS browser origins allowed to call the portal API."
  type        = set(string)

  validation {
    condition = length(var.portal_cors_allowed_origins) > 0 && alltrue([
      for origin in var.portal_cors_allowed_origins : can(regex("^https://[^/?# ]+(:[0-9]{1,5})?$", origin))
    ])
    error_message = "portal_cors_allowed_origins must contain at least one exact HTTPS origin without a path."
  }
}

variable "lambda_memory_mb" {
  type    = number
  default = 512

  validation {
    condition     = var.lambda_memory_mb >= 128 && var.lambda_memory_mb <= 10240
    error_message = "lambda_memory_mb must be between 128 and 10240."
  }
}

variable "lambda_ephemeral_storage_mb" {
  type    = number
  default = 512

  validation {
    condition     = var.lambda_ephemeral_storage_mb >= 512 && var.lambda_ephemeral_storage_mb <= 10240
    error_message = "lambda_ephemeral_storage_mb must be between 512 and 10240."
  }
}

variable "lambda_reserved_concurrency" {
  type    = number
  default = 5

  validation {
    condition     = var.lambda_reserved_concurrency >= 1
    error_message = "lambda_reserved_concurrency must be at least 1."
  }
}

variable "portal_chat_timeout_seconds" {
  type    = number
  default = 29

  validation {
    condition     = var.portal_chat_timeout_seconds >= 1 && var.portal_chat_timeout_seconds <= 29
    error_message = "portal_chat_timeout_seconds must be between 1 and 29."
  }
}

variable "portal_readiness_timeout_seconds" {
  type    = number
  default = 2

  validation {
    condition     = var.portal_readiness_timeout_seconds >= 1 && var.portal_readiness_timeout_seconds <= 10
    error_message = "portal_readiness_timeout_seconds must be between 1 and 10."
  }
}

variable "portal_chat_max_concurrency" {
  type    = number
  default = 18

  validation {
    condition     = var.portal_chat_max_concurrency >= 1 && var.portal_chat_max_concurrency <= 64
    error_message = "portal_chat_max_concurrency must be between 1 and 64."
  }
}

variable "portal_page_size" {
  type    = number
  default = 50

  validation {
    condition     = var.portal_page_size >= 1 && var.portal_page_size <= 100
    error_message = "portal_page_size must be between 1 and 100."
  }
}

variable "portal_max_detail_bytes" {
  type    = number
  default = 262144

  validation {
    condition     = var.portal_max_detail_bytes >= 1 && var.portal_max_detail_bytes <= 10485760
    error_message = "portal_max_detail_bytes must be between 1 and 10485760."
  }
}

variable "chat_history_enabled" {
  description = "Create bounded DynamoDB chat history tables and enable persistent chat state."
  type        = bool
  default     = false
}

variable "chat_history_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = var.chat_history_retention_days >= 1 && var.chat_history_retention_days <= 3650
    error_message = "chat_history_retention_days must be between 1 and 3650."
  }
}

variable "chat_max_sessions_per_user" {
  type    = number
  default = 10

  validation {
    condition     = var.chat_max_sessions_per_user >= 1 && var.chat_max_sessions_per_user <= 100
    error_message = "chat_max_sessions_per_user must be between 1 and 100."
  }
}

variable "chat_max_messages_per_session" {
  type    = number
  default = 30

  validation {
    condition     = var.chat_max_messages_per_session >= 1 && var.chat_max_messages_per_session <= 200
    error_message = "chat_max_messages_per_session must be between 1 and 200."
  }
}

variable "chat_max_stored_message_bytes" {
  type    = number
  default = 4000

  validation {
    condition     = var.chat_max_stored_message_bytes >= 1 && var.chat_max_stored_message_bytes <= 65536
    error_message = "chat_max_stored_message_bytes must be between 1 and 65536."
  }
}

variable "chat_images_enabled" {
  type    = bool
  default = false
}

variable "log_retention_days" {
  type    = number
  default = 30

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days must be a CloudWatch Logs supported retention value."
  }
}

variable "alarm_notification_topic_arns" {
  description = "SNS topic ARNs notified by portal alarms."
  type        = set(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.alarm_notification_topic_arns : can(regex("^arn:aws:sns:us-east-1:[0-9]{12}:[A-Za-z0-9_-]+$", arn))
    ])
    error_message = "Every alarm notification target must be a commercial us-east-1 SNS topic ARN."
  }
}

variable "api_throttle_burst_limit" {
  type    = number
  default = 50

  validation {
    condition     = var.api_throttle_burst_limit >= 1 && var.api_throttle_burst_limit <= 10000
    error_message = "api_throttle_burst_limit must be between 1 and 10000."
  }
}

variable "api_throttle_rate_limit" {
  type    = number
  default = 100

  validation {
    condition     = var.api_throttle_rate_limit >= 1 && var.api_throttle_rate_limit <= 10000
    error_message = "api_throttle_rate_limit must be between 1 and 10000."
  }
}
