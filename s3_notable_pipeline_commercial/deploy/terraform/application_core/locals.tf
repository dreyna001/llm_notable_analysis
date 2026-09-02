data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region
  account_id = data.aws_caller_identity.current.account_id

  analyzer_function_name = "${var.name_prefix}-analyzer-s3"
  embed_function_name    = "${var.name_prefix}-case-embed"
  rag_function_name      = "${var.name_prefix}-rag-ingestion"

  analyzer_role_name = "${var.name_prefix}-analyzer-role"
  embed_role_name    = "${var.name_prefix}-case-embed-role"
  rag_role_name      = "${var.name_prefix}-rag-ingestion-role"

  archive_bucket_name = coalesce(var.case_archive_bucket_name, var.output_bucket_name)
  rag_source_bucket   = coalesce(var.rag_source_bucket_name, var.input_bucket_name)
  vpc_enabled         = length(var.subnet_ids) > 0 && length(var.security_group_ids) > 0
  alarm_actions       = var.alarm_notification_topic_arn == null ? [] : [var.alarm_notification_topic_arn]
  kms_enabled         = var.kms_key_arn != null

  common_lambda_environment = {
    AWS_PARTITION               = local.partition
    CUSTOMER_KMS_KEY_ARN        = var.kms_key_arn == null ? "" : var.kms_key_arn
    CUSTOMER_VPC_SUBNET_IDS     = join(",", var.subnet_ids)
    CUSTOMER_SECURITY_GROUP_IDS = join(",", var.security_group_ids)
    RAG_TENANT_ID               = var.rag_tenant_id
    RAG_RETRIEVAL_BACKEND       = "opensearch"
    OPENSEARCH_ENDPOINT         = var.opensearch_endpoint
    OPENSEARCH_REGION           = local.region
    OPENSEARCH_SERVICE          = "es"
    OPENSEARCH_CASE_INDEX       = var.opensearch_indexes.case_chunks
    OPENSEARCH_SOC_INDEX        = var.opensearch_indexes.soc_knowledge
    OPENSEARCH_SPLUNK_INDEX     = var.opensearch_indexes.splunk_dictionary
    OPENSEARCH_ELASTIC_INDEX    = var.opensearch_indexes.elastic_dictionary
  }

  analyzer_environment = merge(local.common_lambda_environment, {
    ANALYZER_QUEUE_URL                = aws_sqs_queue.analyzer.id
    CASE_EMBED_QUEUE_URL              = var.features.case_qa ? aws_sqs_queue.embed[0].id : ""
    RAG_INGEST_QUEUE_URL              = var.features.rag_ingestion ? aws_sqs_queue.rag[0].id : ""
    CAPABILITY_PROFILES               = join(",", compact(["core", var.features.rag ? "rag" : ""]))
    ALLOW_PRIVATE_OUTBOUND_ENDPOINTS  = "false"
    HTML_REPORT_ENABLED               = tostring(var.features.html_report)
    RAG_ENABLED                       = tostring(var.features.rag)
    RAG_MAX_SNIPPETS                  = tostring(var.rag_settings.max_snippets)
    RAG_CONTEXT_BUDGET_CHARS          = tostring(var.rag_settings.context_budget_chars)
    RAG_FAILURE_MODE                  = var.rag_settings.failure_mode
    BEDROCK_MODEL_ID                  = var.bedrock_analysis_model_id
    SPLUNK_SINK_MODE                  = "s3"
    SPL_QUERY_RAG_ENABLED             = "false"
    CASE_ARCHIVE_ENABLED              = tostring(var.features.case_archive)
    CASE_ARCHIVE_FAILURE_MODE         = var.case_settings.archive_failure_mode
    CASE_ARCHIVE_BUCKET               = local.archive_bucket_name
    CASE_ARCHIVE_PREFIX               = var.case_settings.archive_prefix
    CASE_ARCHIVE_CHUNKS_PREFIX        = var.case_settings.chunks_prefix
    CASE_INDEX_TABLE                  = var.features.case_qa ? aws_dynamodb_table.case_index[0].name : ""
    CASE_RETENTION_DAYS               = tostring(var.retention.case_days)
    CASE_SCHEMA_VERSION               = tostring(var.case_settings.schema_version)
    CASE_ANALYSIS_SCHEMA_VERSION      = tostring(var.case_settings.analysis_schema_version)
    CASE_ARCHIVE_MAX_ALERT_BYTES      = tostring(var.case_settings.max_alert_bytes)
    CASE_ARCHIVE_MAX_ANALYSIS_BYTES   = tostring(var.case_settings.max_analysis_bytes)
    PORTAL_ENABLED                    = "false"
    CASE_QA_ENABLED                   = tostring(var.features.case_qa)
    CASE_QA_GENERAL_KNOWLEDGE_ENABLED = "true"
    CASE_QA_MAX_INDEX_CHUNKS_PER_CASE = tostring(var.case_settings.max_index_chunks_per_case)
    CASE_QA_EMBEDDING_MODEL           = var.case_settings.embedding_model
    CASE_QA_VECTOR_DIMENSIONS         = tostring(var.case_settings.vector_dimensions)
    CASE_QA_EMBED_NORMALIZE           = tostring(var.case_settings.embed_normalize)
    INPUT_BUCKET_NAME                 = aws_s3_bucket.input.bucket
    OUTPUT_BUCKET_NAME                = aws_s3_bucket.output.bucket
    OUTPUT_PREFIX                     = "reports"
    MAX_DECOMPRESSED_INPUT_BYTES      = tostring(var.max_decompressed_input_bytes)
    MAX_COMPRESSED_INPUT_BYTES        = tostring(var.max_compressed_input_bytes)
  })

  embed_environment = merge(local.common_lambda_environment, {
    CASE_EMBED_QUEUE_URL              = try(aws_sqs_queue.embed[0].id, "")
    CAPABILITY_PROFILES               = "core"
    CASE_ARCHIVE_BUCKET               = local.archive_bucket_name
    CASE_ARCHIVE_PREFIX               = var.case_settings.archive_prefix
    CASE_ARCHIVE_CHUNKS_PREFIX        = var.case_settings.chunks_prefix
    CASE_INDEX_TABLE                  = try(aws_dynamodb_table.case_index[0].name, "")
    CASE_QA_MAX_INDEX_CHUNKS_PER_CASE = tostring(var.case_settings.max_index_chunks_per_case)
    CASE_QA_EMBEDDING_MODEL           = var.case_settings.embedding_model
    CASE_QA_VECTOR_DIMENSIONS         = tostring(var.case_settings.vector_dimensions)
    CASE_QA_EMBED_NORMALIZE           = tostring(var.case_settings.embed_normalize)
  })

  rag_environment = merge(local.common_lambda_environment, {
    RAG_INGEST_QUEUE_URL                   = try(aws_sqs_queue.rag[0].id, "")
    RAG_INGEST_MAX_DOCUMENT_BYTES          = tostring(var.rag_settings.max_document_bytes)
    RAG_INGEST_MAX_MANIFEST_BYTES          = tostring(var.rag_settings.max_manifest_bytes)
    RAG_INGEST_MAX_DOCUMENTS_PER_MANIFEST  = tostring(var.rag_settings.max_documents_per_manifest)
    RAG_INGEST_MAX_TOTAL_SOURCE_BYTES      = tostring(var.rag_settings.max_total_source_bytes)
    RAG_INGEST_MAX_EMBEDDINGS_PER_MANIFEST = tostring(var.rag_settings.max_embeddings_per_manifest)
    KB_EXTRACT_MAX_BYTES                   = tostring(var.rag_settings.extract_max_bytes)
    KB_EXTRACT_MAX_PDF_PAGES               = tostring(var.rag_settings.extract_max_pdf_pages)
    KB_EXTRACT_MAX_OUTPUT_CHARS            = tostring(var.rag_settings.extract_max_output_chars)
    RAG_SOURCE_BUCKET                      = local.rag_source_bucket
    RAG_SOURCE_PREFIX                      = var.rag_settings.source_prefix
    CASE_QA_EMBEDDING_MODEL                = var.case_settings.embedding_model
  })

  tags = merge({
    Application = "llm-notable-analysis"
    ManagedBy   = "Terraform"
  }, var.tags)
}

resource "terraform_data" "validate_contract" {
  lifecycle {
    precondition {
      condition     = (length(var.subnet_ids) == 0) == (length(var.security_group_ids) == 0)
      error_message = "subnet_ids and security_group_ids must either both be empty or both be supplied."
    }

    precondition {
      condition     = local.region == "us-east-1" && local.partition == "aws"
      error_message = "The commercial customer-default module must run in the aws partition and us-east-1."
    }

    precondition {
      condition     = !var.features.case_qa || var.features.case_archive
      error_message = "case_qa requires case_archive so chunks have a canonical source."
    }

    precondition {
      condition     = var.rag_source_bucket_name == null || var.rag_source_bucket_name != var.input_bucket_name
      error_message = "rag_source_bucket_name must be null or different from input_bucket_name."
    }
  }
}
