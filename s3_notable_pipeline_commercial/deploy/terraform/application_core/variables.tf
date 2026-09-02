variable "name_prefix" {
  description = "Prefix used for deterministic resource names."
  type        = string
  default     = "notable"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-32 lowercase letters, numbers, or hyphens, starting with a letter."
  }
}

variable "image_uri" {
  description = "Immutable ECR image URI used by every Lambda function."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}\\.dkr\\.ecr\\.us-east-1\\.amazonaws\\.com/[A-Za-z0-9._/-]+@sha256:[a-f0-9]{64}$", var.image_uri))
    error_message = "image_uri must be a us-east-1 ECR URI pinned to a sha256 digest."
  }
}

variable "input_bucket_name" {
  description = "Globally unique name for the managed input bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.input_bucket_name)) && !can(regex("\\.\\.", var.input_bucket_name))
    error_message = "input_bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "output_bucket_name" {
  description = "Globally unique name for the managed output and default case archive bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.output_bucket_name)) && !can(regex("\\.\\.", var.output_bucket_name))
    error_message = "output_bucket_name must be a valid 3-63 character S3 bucket name."
  }
}

variable "case_archive_bucket_name" {
  description = "Existing case archive bucket override. Null uses the managed output bucket."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.case_archive_bucket_name == null || (can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.case_archive_bucket_name)) && !can(regex("\\.\\.", var.case_archive_bucket_name)))
    error_message = "case_archive_bucket_name must be null or a valid S3 bucket name."
  }
}

variable "rag_source_bucket_name" {
  description = "Existing RAG source bucket. Null uses the managed input bucket and configures its manifest notification."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.rag_source_bucket_name == null || (can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.rag_source_bucket_name)) && !can(regex("\\.\\.", var.rag_source_bucket_name)))
    error_message = "rag_source_bucket_name must be null or a valid S3 bucket name."
  }
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key ARN. Null uses S3 AES-256, DynamoDB service encryption, and SQS managed encryption."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.kms_key_arn == null || can(regex("^arn:aws:kms:us-east-1:[0-9]{12}:key/[A-Fa-f0-9-]+$", var.kms_key_arn))
    error_message = "kms_key_arn must be a commercial us-east-1 KMS key ARN."
  }
}

variable "subnet_ids" {
  description = "Private subnet IDs for Lambda VPC attachment. Supply together with security_group_ids."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for id in var.subnet_ids : can(regex("^subnet-[0-9a-f]+$", id))])
    error_message = "Every subnet ID must start with subnet-."
  }
}

variable "security_group_ids" {
  description = "Security group IDs for Lambda VPC attachment. Supply together with subnet_ids."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for id in var.security_group_ids : can(regex("^sg-[0-9a-f]+$", id))])
    error_message = "Every security group ID must start with sg-."
  }
}

variable "bedrock_analysis_model_id" {
  description = "Customer-approved Bedrock analysis model or inference profile ID."
  type        = string

  validation {
    condition     = trimspace(var.bedrock_analysis_model_id) != ""
    error_message = "bedrock_analysis_model_id cannot be empty."
  }
}

variable "bedrock_analysis_model_arn" {
  description = "Exact least-privilege ARN for the analysis model or inference profile."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:bedrock:us-east-1:([0-9]{12})?:(foundation-model|inference-profile)/.+$", var.bedrock_analysis_model_arn))
    error_message = "bedrock_analysis_model_arn must identify a us-east-1 foundation model or inference profile."
  }
}

variable "bedrock_inference_profile_model_arns" {
  description = "Foundation-model ARNs used through a cross-region inference profile."
  type        = list(string)
  default     = []

  validation {
    condition = alltrue([
      for arn in var.bedrock_inference_profile_model_arns :
      can(regex("^arn:aws:bedrock:[a-z0-9-]+::foundation-model/[A-Za-z0-9._:-]+$", arn))
    ])
    error_message = "Each inference profile model ARN must be a Bedrock foundation-model ARN."
  }
}

variable "opensearch_endpoint" {
  description = "VPC-only OpenSearch HTTPS endpoint with no trailing slash or path."
  type        = string

  validation {
    condition     = can(regex("^https://[A-Za-z0-9.-]+\\.[a-z0-9-]+\\.es\\.amazonaws\\.com$", var.opensearch_endpoint))
    error_message = "opensearch_endpoint must be an https:// AWS OpenSearch domain endpoint without a path or trailing slash."
  }
}

variable "opensearch_domain_arn" {
  description = "ARN of the VPC-only OpenSearch domain."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:es:us-east-1:[0-9]{12}:domain/[A-Za-z0-9_-]+$", var.opensearch_domain_arn))
    error_message = "opensearch_domain_arn must be a commercial us-east-1 domain ARN."
  }
}

variable "rag_tenant_id" {
  description = "Non-empty customer deployment or tenant identifier stored with every search document."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", var.rag_tenant_id))
    error_message = "rag_tenant_id must be 1-128 safe identifier characters."
  }
}

variable "opensearch_indexes" {
  description = "OpenSearch index names used by the core and RAG workers."
  type = object({
    case_chunks        = optional(string, "case_chunks")
    soc_knowledge      = optional(string, "soc_knowledge")
    splunk_dictionary  = optional(string, "splunk_dictionary")
    elastic_dictionary = optional(string, "elastic_dictionary")
  })
  default = {}

  validation {
    condition = alltrue([
      for value in values(var.opensearch_indexes) : can(regex("^[a-z0-9][a-z0-9_-]{0,254}$", value))
    ])
    error_message = "OpenSearch index names must use lowercase letters, numbers, underscores, or hyphens."
  }
}

variable "features" {
  description = "Core feature switches. case_qa creates the embedding worker and requires the case index."
  type = object({
    rag           = optional(bool, true)
    rag_ingestion = optional(bool, true)
    case_archive  = optional(bool, true)
    case_qa       = optional(bool, true)
    html_report   = optional(bool, false)
  })
  default = {}
}

variable "case_index_table_name" {
  description = "Managed case index table name."
  type        = string
  default     = "notable-case-index"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,255}$", var.case_index_table_name))
    error_message = "case_index_table_name must be a valid DynamoDB table name."
  }
}

variable "lambda_settings" {
  description = "Lambda capacity settings for the analyzer and workers."
  type = object({
    timeout_seconds               = optional(number, 360)
    memory_mb                     = optional(number, 512)
    ephemeral_storage_mb          = optional(number, 512)
    analyzer_reserved_concurrency = optional(number, 5)
    analyzer_maximum_concurrency  = optional(number, 5)
    embed_maximum_concurrency     = optional(number, 5)
    rag_reserved_concurrency      = optional(number, 2)
  })
  default = {}

  validation {
    condition = (
      var.lambda_settings.timeout_seconds >= 1 && var.lambda_settings.timeout_seconds <= 900 &&
      var.lambda_settings.memory_mb >= 128 && var.lambda_settings.memory_mb <= 10240 &&
      var.lambda_settings.ephemeral_storage_mb >= 512 && var.lambda_settings.ephemeral_storage_mb <= 10240 &&
      var.lambda_settings.analyzer_reserved_concurrency >= 1 &&
      var.lambda_settings.analyzer_maximum_concurrency >= 2 && var.lambda_settings.analyzer_maximum_concurrency <= 1000 &&
      var.lambda_settings.embed_maximum_concurrency >= 2 && var.lambda_settings.embed_maximum_concurrency <= 1000 &&
      var.lambda_settings.rag_reserved_concurrency >= 2 && var.lambda_settings.rag_reserved_concurrency <= 1000
    )
    error_message = "Lambda timeout, memory, storage, and concurrency values are outside supported bounds."
  }
}

variable "queue_settings" {
  description = "SQS retry and retention settings. Visibility must exceed the longest Lambda timeout."
  type = object({
    visibility_timeout_seconds = optional(number, 960)
    message_retention_seconds  = optional(number, 345600)
    dlq_retention_seconds      = optional(number, 1209600)
    max_receive_count          = optional(number, 3)
  })
  default = {}

  validation {
    condition = (
      var.queue_settings.visibility_timeout_seconds >= 900 && var.queue_settings.visibility_timeout_seconds <= 43200 &&
      var.queue_settings.message_retention_seconds >= 60 && var.queue_settings.message_retention_seconds <= 1209600 &&
      var.queue_settings.dlq_retention_seconds >= 60 && var.queue_settings.dlq_retention_seconds <= 1209600 &&
      var.queue_settings.max_receive_count >= 1 && var.queue_settings.max_receive_count <= 1000
    )
    error_message = "Queue visibility must be at least 900 seconds and all queue settings must be within AWS limits."
  }
}

variable "retention" {
  description = "Data and log retention in days."
  type = object({
    input_days  = optional(number, 2)
    output_days = optional(number, 7)
    case_days   = optional(number, 30)
    log_days    = optional(number, 30)
  })
  default = {}

  validation {
    condition = (
      var.retention.input_days >= 1 && var.retention.input_days <= 365 &&
      var.retention.output_days >= 1 && var.retention.output_days <= 365 &&
      var.retention.case_days >= 1 && var.retention.case_days <= 3650 &&
      contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.retention.log_days)
    )
    error_message = "Retention values are outside supported bounds."
  }
}

variable "rag_settings" {
  description = "Bounded retrieval and ingestion settings matching the SAM customer defaults."
  type = object({
    max_snippets                = optional(number, 4)
    context_budget_chars        = optional(number, 1600)
    failure_mode                = optional(string, "suppress")
    source_prefix               = optional(string, "rag-sources/")
    manifest_prefix             = optional(string, "rag-sources/manifests/")
    max_document_bytes          = optional(number, 5242880)
    max_manifest_bytes          = optional(number, 262144)
    max_documents_per_manifest  = optional(number, 100)
    max_total_source_bytes      = optional(number, 52428800)
    max_embeddings_per_manifest = optional(number, 2000)
    extract_max_bytes           = optional(number, 10485760)
    extract_max_pdf_pages       = optional(number, 50)
    extract_max_output_chars    = optional(number, 12000)
  })
  default = {}

  validation {
    condition     = contains(["suppress", "fail_closed"], var.rag_settings.failure_mode)
    error_message = "rag_settings.failure_mode must be suppress or fail_closed."
  }
}

variable "case_settings" {
  description = "Case archive and embedding settings matching the SAM customer defaults."
  type = object({
    archive_failure_mode      = optional(string, "suppress")
    archive_prefix            = optional(string, "cases")
    chunks_prefix             = optional(string, "case_chunks")
    schema_version            = optional(number, 1)
    analysis_schema_version   = optional(number, 1)
    max_alert_bytes           = optional(number, 262144)
    max_analysis_bytes        = optional(number, 524288)
    max_index_chunks_per_case = optional(number, 200)
    embedding_model           = optional(string, "amazon.titan-embed-text-v2:0")
    vector_dimensions         = optional(number, 1024)
    embed_normalize           = optional(bool, true)
  })
  default = {}

  validation {
    condition     = contains(["suppress", "fail_closed"], var.case_settings.archive_failure_mode)
    error_message = "case_settings.archive_failure_mode must be suppress or fail_closed."
  }
}

variable "max_decompressed_input_bytes" {
  description = "Maximum decompressed bytes accepted for one gzip notable."
  type        = number
  default     = 1048576

  validation {
    condition     = var.max_decompressed_input_bytes >= 1 && var.max_decompressed_input_bytes <= 20971520
    error_message = "max_decompressed_input_bytes must be between 1 and 20 MiB."
  }
}

variable "max_compressed_input_bytes" {
  description = "Maximum compressed bytes read for one gzip notable."
  type        = number
  default     = 2097152

  validation {
    condition     = var.max_compressed_input_bytes >= 1 && var.max_compressed_input_bytes <= 20971520
    error_message = "max_compressed_input_bytes must be between 1 and 20 MiB."
  }
}

variable "alarm_notification_topic_arn" {
  description = "Optional SNS topic ARN for alarm actions."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.alarm_notification_topic_arn == null || can(regex("^arn:aws:sns:us-east-1:[0-9]{12}:[A-Za-z0-9_-]+$", var.alarm_notification_topic_arn))
    error_message = "alarm_notification_topic_arn must be a us-east-1 SNS topic ARN."
  }
}

variable "tags" {
  description = "Tags applied to managed resources."
  type        = map(string)
  default     = {}
}
