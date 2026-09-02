resource "aws_cloudwatch_log_group" "analyzer" {
  name              = "/aws/lambda/${local.analyzer_function_name}"
  retention_in_days = var.retention.log_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "embed" {
  count = var.features.case_qa ? 1 : 0

  name              = "/aws/lambda/${local.embed_function_name}"
  retention_in_days = var.retention.log_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

resource "aws_cloudwatch_log_group" "rag" {
  count = var.features.rag_ingestion ? 1 : 0

  name              = "/aws/lambda/${local.rag_function_name}"
  retention_in_days = var.retention.log_days
  kms_key_id        = var.kms_key_arn
  tags              = local.tags
}

resource "aws_lambda_function" "analyzer" {
  #checkov:skip=CKV_AWS_116:SQS redrive policies provide per-record retry and DLQ handling for this event-source Lambda.
  #checkov:skip=CKV_AWS_272:Lambda code-signing configurations support Zip packages, not container images.
  #checkov:skip=CKV_AWS_173:The customer-default root supplies kms_key_id; the reusable module permits identifier-only environment data with AWS-managed encryption.
  function_name = local.analyzer_function_name
  description   = "Analyze S3 notables with the customer-approved Bedrock model"
  role          = aws_iam_role.analyzer.arn
  package_type  = "Image"
  image_uri     = var.image_uri

  timeout                        = var.lambda_settings.timeout_seconds
  memory_size                    = var.lambda_settings.memory_mb
  reserved_concurrent_executions = var.lambda_settings.analyzer_reserved_concurrency

  ephemeral_storage {
    size = var.lambda_settings.ephemeral_storage_mb
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.analyzer_environment
  }

  dynamic "vpc_config" {
    for_each = local.vpc_enabled ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.analyzer,
    aws_iam_role_policy.analyzer,
    terraform_data.validate_contract,
  ]

  tags = local.tags
}

resource "aws_lambda_event_source_mapping" "analyzer" {
  event_source_arn        = aws_sqs_queue.analyzer.arn
  function_name           = aws_lambda_function.analyzer.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.lambda_settings.analyzer_maximum_concurrency
  }
}

resource "aws_lambda_function" "embed" {
  #checkov:skip=CKV_AWS_116:SQS redrive policies provide per-record retry and DLQ handling for this event-source Lambda.
  #checkov:skip=CKV_AWS_272:Lambda code-signing configurations support Zip packages, not container images.
  #checkov:skip=CKV_AWS_173:The customer-default root supplies kms_key_id; the reusable module permits identifier-only environment data with AWS-managed encryption.
  count = var.features.case_qa ? 1 : 0

  function_name = local.embed_function_name
  description   = "Embed archived case chunks and update the case index"
  role          = aws_iam_role.embed[0].arn
  package_type  = "Image"
  image_uri     = var.image_uri

  timeout                        = 900
  memory_size                    = var.lambda_settings.memory_mb
  reserved_concurrent_executions = var.lambda_settings.embed_reserved_concurrency

  ephemeral_storage {
    size = var.lambda_settings.ephemeral_storage_mb
  }

  tracing_config {
    mode = "Active"
  }

  image_config {
    command = ["s3_notable_pipeline.embed_handler.handler"]
  }

  environment {
    variables = local.embed_environment
  }

  dynamic "vpc_config" {
    for_each = local.vpc_enabled ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.embed,
    aws_iam_role_policy.embed,
    terraform_data.validate_contract,
  ]

  tags = local.tags
}

resource "aws_lambda_event_source_mapping" "embed" {
  count = var.features.case_qa ? 1 : 0

  event_source_arn        = aws_sqs_queue.embed[0].arn
  function_name           = aws_lambda_function.embed[0].arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.lambda_settings.embed_maximum_concurrency
  }
}

resource "aws_lambda_function" "rag" {
  #checkov:skip=CKV_AWS_116:SQS redrive policies provide per-record retry and DLQ handling for this event-source Lambda.
  #checkov:skip=CKV_AWS_272:Lambda code-signing configurations support Zip packages, not container images.
  #checkov:skip=CKV_AWS_173:The customer-default root supplies kms_key_id; the reusable module permits identifier-only environment data with AWS-managed encryption.
  count = var.features.rag_ingestion ? 1 : 0

  function_name = local.rag_function_name
  description   = "Validate and ingest private RAG manifests into OpenSearch"
  role          = aws_iam_role.rag[0].arn
  package_type  = "Image"
  image_uri     = var.image_uri

  timeout                        = var.lambda_settings.timeout_seconds
  memory_size                    = var.lambda_settings.memory_mb
  reserved_concurrent_executions = var.lambda_settings.rag_reserved_concurrency

  image_config {
    command = ["s3_notable_pipeline.rag_ingest_handler.handler"]
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = local.rag_environment
  }

  dynamic "vpc_config" {
    for_each = local.vpc_enabled ? [1] : []
    content {
      subnet_ids         = var.subnet_ids
      security_group_ids = var.security_group_ids
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.rag,
    aws_iam_role_policy.rag,
    terraform_data.validate_contract,
  ]

  tags = local.tags
}

resource "aws_lambda_event_source_mapping" "rag" {
  count = var.features.rag_ingestion ? 1 : 0

  event_source_arn        = aws_sqs_queue.rag[0].arn
  function_name           = aws_lambda_function.rag[0].arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.lambda_settings.rag_reserved_concurrency
  }
}
