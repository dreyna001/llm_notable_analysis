data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  function_name = "${var.name_prefix}-portal-api"
  role_name     = "${var.name_prefix}-portal-api-role"

  case_index_arn     = var.case_index_table_arn
  chat_sessions_arn  = var.chat_history_enabled ? aws_dynamodb_table.chat_sessions[0].arn : null
  chat_messages_arn  = var.chat_history_enabled ? aws_dynamodb_table.chat_messages[0].arn : null
  chat_sessions_name = var.chat_history_enabled ? aws_dynamodb_table.chat_sessions[0].name : ""
  chat_messages_name = var.chat_history_enabled ? aws_dynamodb_table.chat_messages[0].name : ""

  selected_chat_model_arn = var.portal_chat_model_arn != "" ? var.portal_chat_model_arn : var.bedrock_analysis_model_arn
  selected_chat_foundation_model_arns = var.portal_chat_model_arn != "" ? (
    var.portal_chat_inference_profile_foundation_model_arns
  ) : var.bedrock_analysis_inference_profile_foundation_model_arns

  portal_environment = {
    AWS_PARTITION                       = data.aws_partition.current.partition
    CUSTOMER_KMS_KEY_ARN                = var.kms_key_arn == null ? "" : var.kms_key_arn
    CUSTOMER_VPC_SUBNET_IDS             = join(",", var.subnet_ids)
    CUSTOMER_SECURITY_GROUP_IDS         = join(",", var.security_group_ids)
    CAPABILITY_PROFILES                 = var.capability_profiles
    BEDROCK_MODEL_ID                    = var.bedrock_analysis_model_id
    RAG_TENANT_ID                       = var.rag_tenant_id
    RAG_RETRIEVAL_BACKEND               = "opensearch"
    OPENSEARCH_ENDPOINT                 = var.opensearch_endpoint
    OPENSEARCH_REGION                   = var.aws_region
    OPENSEARCH_SERVICE                  = "es"
    OPENSEARCH_CASE_INDEX               = var.opensearch_case_index
    OPENSEARCH_SOC_INDEX                = var.opensearch_soc_index
    OPENSEARCH_SPLUNK_INDEX             = var.opensearch_splunk_index
    RAG_ENABLED                         = "true"
    RAG_MAX_SNIPPETS                    = "4"
    RAG_CONTEXT_BUDGET_CHARS            = "1600"
    SPL_QUERY_RAG_ENABLED               = "true"
    CASE_ARCHIVE_BUCKET                 = var.output_bucket_name
    CASE_ARCHIVE_PREFIX                 = var.case_archive_prefix
    CASE_ARCHIVE_CHUNKS_PREFIX          = var.case_archive_chunks_prefix
    CASE_EMBED_QUEUE_URL                = var.case_embed_queue_url
    CASE_INDEX_TABLE                    = var.case_index_table_name
    CASE_RETENTION_DAYS                 = tostring(var.case_retention_days)
    PORTAL_ENABLED                      = "true"
    PORTAL_AUTH_MODE                    = var.portal_auth_mode
    PORTAL_PAGE_SIZE                    = tostring(var.portal_page_size)
    PORTAL_MAX_DETAIL_BYTES             = tostring(var.portal_max_detail_bytes)
    PORTAL_JWT_ISSUER                   = var.portal_jwt_issuer
    PORTAL_JWT_AUDIENCE                 = var.portal_jwt_audience
    PORTAL_JWT_TENANT_ID                = var.portal_jwt_tenant_id
    PORTAL_CORS_ALLOWED_ORIGINS         = join(",", sort(tolist(var.portal_cors_allowed_origins)))
    PORTAL_REQUIRED_ANALYST_ROLE        = var.portal_required_analyst_role
    PORTAL_REQUIRED_ANALYST_SCOPE       = var.portal_required_analyst_scope
    PORTAL_UI_BUCKET                    = aws_s3_bucket.portal_ui.id
    PORTAL_CHAT_TIMEOUT_SEC             = tostring(var.portal_chat_timeout_seconds)
    PORTAL_READINESS_TIMEOUT_SECONDS    = tostring(var.portal_readiness_timeout_seconds)
    PORTAL_CHAT_MAX_CONCURRENCY         = tostring(var.portal_chat_max_concurrency)
    PORTAL_CHAT_BEDROCK_MODEL_ID        = var.portal_chat_model_id
    PORTAL_CHAT_VISION_BEDROCK_MODEL_ID = var.portal_chat_vision_model_id
    CASE_QA_ENABLED                     = "true"
    CASE_QA_GENERAL_KNOWLEDGE_ENABLED   = "true"
    CASE_QA_MAX_QUESTION_CHARS          = "2000"
    CASE_QA_MAX_ANSWER_TOKENS           = "800"
    CASE_QA_EMBEDDING_MODEL             = var.case_qa_embedding_model
    CASE_QA_VECTOR_DIMENSIONS           = "1024"
    CASE_QA_EMBED_NORMALIZE             = "true"
    CASE_QA_CHAT_HISTORY_ENABLED        = tostring(var.chat_history_enabled)
    CASE_QA_CHAT_HISTORY_RETENTION_DAYS = tostring(var.chat_history_retention_days)
    CASE_QA_MAX_SESSIONS_PER_USER       = tostring(var.chat_max_sessions_per_user)
    CASE_QA_MAX_MESSAGES_PER_SESSION    = tostring(var.chat_max_messages_per_session)
    CASE_QA_MAX_STORED_MESSAGE_BYTES    = tostring(var.chat_max_stored_message_bytes)
    CASE_QA_CHAT_IMAGES_ENABLED         = tostring(var.chat_images_enabled)
    CASE_QA_MAX_CHAT_IMAGES             = "1"
    CASE_QA_MAX_CHAT_IMAGE_BYTES        = "750000"
    CASE_QA_MAX_CHAT_IMAGE_DIMENSION    = "4096"
    CASE_QA_MAX_CHAT_IMAGE_PIXELS       = "16777216"
    RAG_RERANK_ENABLED                  = "false"
    CHAT_SESSIONS_TABLE                 = local.chat_sessions_name
    CHAT_MESSAGES_TABLE                 = local.chat_messages_name
  }
}

resource "aws_dynamodb_table" "chat_sessions" {
  count = var.chat_history_enabled ? 1 : 0

  name         = "${var.name_prefix}-chat-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "updated_at_session_id"
    type = "S"
  }

  global_secondary_index {
    name = "UserUpdatedIndex"

    key_schema {
      attribute_name = "user_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "updated_at_session_id"
      key_type       = "RANGE"
    }

    projection_type = "ALL"
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-chat-sessions" })
}

resource "aws_dynamodb_table" "chat_messages" {
  count = var.chat_history_enabled ? 1 : 0

  name         = "${var.name_prefix}-chat-messages"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "created_at_message_id"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "created_at_message_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-chat-messages" })
}

resource "aws_s3_bucket" "portal_ui" {
  bucket = var.portal_ui_bucket_name
  tags   = merge(var.tags, { Name = var.portal_ui_bucket_name })
}

resource "aws_s3_bucket_public_access_block" "portal_ui" {
  bucket = aws_s3_bucket.portal_ui.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "portal_ui" {
  bucket = aws_s3_bucket.portal_ui.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "portal_ui" {
  bucket = aws_s3_bucket.portal_ui.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "portal_ui" {
  bucket = aws_s3_bucket.portal_ui.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "portal" {
  name               = local.role_name
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  tags               = merge(var.tags, { Name = local.role_name })
}

data "aws_iam_policy_document" "portal" {
  statement {
    sid     = "WriteFunctionLogs"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.portal.arn}:*",
    ]
  }

  statement {
    sid    = "ReadCaseIndex"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [
      local.case_index_arn,
      "${local.case_index_arn}/index/ProcessedAtIndex",
    ]
  }

  statement {
    sid     = "ReadCaseArchiveObjects"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.output_bucket_name}/${var.case_archive_prefix}/*",
      "arn:${data.aws_partition.current.partition}:s3:::${var.output_bucket_name}/${var.case_archive_chunks_prefix}/*",
      "arn:${data.aws_partition.current.partition}:s3:::${var.output_bucket_name}/reports/*",
    ]
  }

  statement {
    sid     = "ListCaseArchive"
    effect  = "Allow"
    actions = ["s3:ListBucket"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::${var.output_bucket_name}",
    ]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        var.case_archive_prefix,
        "${var.case_archive_prefix}/*",
      ]
    }
  }

  statement {
    sid       = "ReadPortalUi"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.portal_ui.arn}/*"]
  }

  statement {
    sid    = "InvokePortalChatModel"
    effect = "Allow"
    actions = [
      "bedrock:CountTokens",
      "bedrock:InvokeModel",
    ]
    resources = [local.selected_chat_model_arn]
  }

  dynamic "statement" {
    for_each = length(local.selected_chat_foundation_model_arns) > 0 ? [1] : []
    content {
      sid       = "InvokePortalChatInferenceProfileModels"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel"]
      resources = sort(tolist(local.selected_chat_foundation_model_arns))
      condition {
        test     = "StringEquals"
        variable = "bedrock:InferenceProfileArn"
        values   = [local.selected_chat_model_arn]
      }
    }
  }

  statement {
    sid       = "CreateCaseQuestionEmbeddings"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = ["arn:${data.aws_partition.current.partition}:bedrock:${var.aws_region}::foundation-model/${var.case_qa_embedding_model}"]
  }

  dynamic "statement" {
    for_each = var.portal_chat_vision_model_arn != "" && var.portal_chat_vision_model_arn != local.selected_chat_model_arn ? [1] : []
    content {
      sid       = "InvokePortalVisionModel"
      effect    = "Allow"
      actions   = ["bedrock:CountTokens", "bedrock:InvokeModel"]
      resources = [var.portal_chat_vision_model_arn]
    }
  }

  dynamic "statement" {
    for_each = length(var.portal_chat_vision_inference_profile_foundation_model_arns) > 0 ? [1] : []
    content {
      sid       = "InvokePortalVisionInferenceProfileModels"
      effect    = "Allow"
      actions   = ["bedrock:InvokeModel"]
      resources = sort(tolist(var.portal_chat_vision_inference_profile_foundation_model_arns))
      condition {
        test     = "StringEquals"
        variable = "bedrock:InferenceProfileArn"
        values   = [var.portal_chat_vision_model_arn]
      }
    }
  }

  statement {
    sid     = "ReadOpenSearch"
    effect  = "Allow"
    actions = ["es:ESHttpGet", "es:ESHttpPost"]
    resources = [
      "${var.opensearch_domain_arn}/*",
    ]
  }

  dynamic "statement" {
    for_each = var.chat_history_enabled ? [1] : []
    content {
      sid    = "ManageChatHistory"
      effect = "Allow"
      actions = [
        "dynamodb:DeleteItem",
        "dynamodb:DescribeTable",
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:UpdateItem",
      ]
      resources = [
        local.chat_sessions_arn,
        "${local.chat_sessions_arn}/index/*",
        local.chat_messages_arn,
      ]
    }
  }

  dynamic "statement" {
    for_each = var.chat_history_enabled ? [1] : []
    content {
      sid       = "WriteChatHistoryTransactions"
      effect    = "Allow"
      actions   = ["dynamodb:TransactWriteItems"]
      resources = [local.chat_sessions_arn, local.chat_messages_arn]
    }
  }

  dynamic "statement" {
    for_each = var.kms_key_arn == null ? [] : [1]
    content {
      sid       = "UseCustomerEncryptionKey"
      effect    = "Allow"
      actions   = ["kms:Decrypt", "kms:DescribeKey"]
      resources = [var.kms_key_arn]
    }
  }

  statement {
    sid    = "ManageVpcNetworkInterfaces"
    effect = "Allow"
    actions = [
      "ec2:AssignPrivateIpAddresses",
      "ec2:CreateNetworkInterface",
      "ec2:DeleteNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:UnassignPrivateIpAddresses",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "portal" {
  name   = "${var.name_prefix}-portal-runtime"
  role   = aws_iam_role.portal.id
  policy = data.aws_iam_policy_document.portal.json
}

resource "aws_cloudwatch_log_group" "portal" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = merge(var.tags, { Name = "/aws/lambda/${local.function_name}" })
}

resource "aws_lambda_function" "portal" {
  function_name = local.function_name
  description   = "Read-only analyst portal API and bounded Case Q&A"
  role          = aws_iam_role.portal.arn
  package_type  = "Image"
  image_uri     = var.image_uri
  timeout       = var.portal_chat_timeout_seconds
  memory_size   = var.lambda_memory_mb

  reserved_concurrent_executions = var.lambda_reserved_concurrency
  kms_key_arn                    = var.kms_key_arn

  image_config {
    command = ["s3_notable_pipeline.portal_handler.handler"]
  }

  ephemeral_storage {
    size = var.lambda_ephemeral_storage_mb
  }

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  environment {
    variables = local.portal_environment
  }

  tags = merge(var.tags, { Name = local.function_name })

  depends_on = [
    aws_cloudwatch_log_group.portal,
    aws_iam_role_policy.portal,
    aws_s3_bucket_public_access_block.portal_ui,
    aws_s3_bucket_server_side_encryption_configuration.portal_ui,
  ]

  lifecycle {
    precondition {
      condition     = data.aws_partition.current.partition == "aws"
      error_message = "The commercial portal module must run in partition aws."
    }

    precondition {
      condition     = data.aws_region.current.region == var.aws_region
      error_message = "The active AWS provider region must match aws_region."
    }

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "The active AWS account must match aws_account_id."
    }

    precondition {
      condition     = length(var.subnet_ids) > 0 && length(var.security_group_ids) > 0
      error_message = "The customer-default VPC-only portal requires subnet_ids and security_group_ids."
    }

    precondition {
      condition = var.portal_auth_mode != "jwt" || (
        var.portal_jwt_issuer != "" &&
        var.portal_jwt_audience != "" &&
        (var.portal_required_analyst_role != "" || var.portal_required_analyst_scope != "")
      )
      error_message = "JWT auth requires issuer, audience, and an analyst role or scope."
    }

    precondition {
      condition     = (var.portal_chat_model_id == "") == (var.portal_chat_model_arn == "")
      error_message = "portal_chat_model_id and portal_chat_model_arn must either both be set or both be empty."
    }

    precondition {
      condition     = var.portal_chat_model_arn != "" || length(var.portal_chat_inference_profile_foundation_model_arns) == 0
      error_message = "portal_chat_inference_profile_foundation_model_arns requires a portal chat model override."
    }

    precondition {
      condition     = (var.portal_chat_vision_model_id == "") == (var.portal_chat_vision_model_arn == "")
      error_message = "portal_chat_vision_model_id and portal_chat_vision_model_arn must either both be set or both be empty."
    }

    precondition {
      condition     = var.portal_chat_vision_model_arn != "" || length(var.portal_chat_vision_inference_profile_foundation_model_arns) == 0
      error_message = "portal_chat_vision_inference_profile_foundation_model_arns requires a vision model override."
    }

    precondition {
      condition     = split(":", var.opensearch_domain_arn)[4] == var.aws_account_id
      error_message = "opensearch_domain_arn must belong to aws_account_id."
    }

    precondition {
      condition = (
        split(":", var.case_index_table_arn)[4] == var.aws_account_id &&
        endswith(var.case_index_table_arn, "/${var.case_index_table_name}")
      )
      error_message = "case_index_table_arn must belong to aws_account_id and match case_index_table_name."
    }

    precondition {
      condition     = split("/", var.case_embed_queue_url)[3] == var.aws_account_id
      error_message = "case_embed_queue_url must belong to aws_account_id."
    }

    precondition {
      condition     = split(".", var.image_uri)[0] == var.aws_account_id
      error_message = "image_uri must belong to aws_account_id."
    }

    precondition {
      condition     = var.kms_key_arn == null || split(":", var.kms_key_arn)[4] == var.aws_account_id
      error_message = "kms_key_arn must belong to aws_account_id."
    }
  }
}

resource "aws_apigatewayv2_api" "portal" {
  name          = "${var.name_prefix}-portal-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_credentials = true
    allow_headers     = ["authorization", "content-type"]
    allow_methods     = ["GET", "POST", "DELETE", "OPTIONS"]
    allow_origins     = sort(tolist(var.portal_cors_allowed_origins))
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-portal-api" })
}

resource "aws_apigatewayv2_integration" "portal" {
  api_id                 = aws_apigatewayv2_api.portal.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.portal.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_authorizer" "portal_jwt" {
  count = var.portal_auth_mode == "jwt" ? 1 : 0

  api_id           = aws_apigatewayv2_api.portal.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "portal-jwt"

  jwt_configuration {
    audience = [var.portal_jwt_audience]
    issuer   = var.portal_jwt_issuer
  }
}

locals {
  protected_route_authorization_type = var.portal_auth_mode == "jwt" ? "JWT" : "AWS_IAM"
  protected_route_authorizer_id      = var.portal_auth_mode == "jwt" ? aws_apigatewayv2_authorizer.portal_jwt[0].id : null
  routes = {
    health = {
      route_key          = "GET /health"
      authorization_type = "NONE"
      authorizer_id      = null
    }
    ready = {
      route_key          = "GET /ready"
      authorization_type = "NONE"
      authorizer_id      = null
    }
    api_proxy = {
      route_key          = "ANY /api/{proxy+}"
      authorization_type = local.protected_route_authorization_type
      authorizer_id      = local.protected_route_authorizer_id
    }
    api_root = {
      route_key          = "ANY /api"
      authorization_type = local.protected_route_authorization_type
      authorizer_id      = local.protected_route_authorizer_id
    }
    static_proxy = {
      route_key          = "GET /{proxy+}"
      authorization_type = "NONE"
      authorizer_id      = null
    }
    static_root = {
      route_key          = "GET /"
      authorization_type = "NONE"
      authorizer_id      = null
    }
  }
}

resource "aws_apigatewayv2_route" "portal" {
  for_each = local.routes

  api_id             = aws_apigatewayv2_api.portal.id
  route_key          = each.value.route_key
  authorization_type = each.value.authorization_type
  authorizer_id      = each.value.authorizer_id
  target             = "integrations/${aws_apigatewayv2_integration.portal.id}"
}

resource "aws_apigatewayv2_stage" "portal" {
  api_id      = aws_apigatewayv2_api.portal.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = var.api_throttle_burst_limit
    throttling_rate_limit  = var.api_throttle_rate_limit
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-portal-default-stage" })
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowPortalApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.portal.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.portal.execution_arn}/*"
}

resource "aws_cloudwatch_metric_alarm" "portal_errors" {
  alarm_name          = "${var.name_prefix}-portal-errors"
  alarm_description   = "Portal Lambda returned an unhandled error."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = sort(tolist(var.alarm_notification_topic_arns))

  dimensions = {
    FunctionName = aws_lambda_function.portal.function_name
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-portal-errors" })
}

resource "aws_cloudwatch_metric_alarm" "portal_api_5xx" {
  alarm_name          = "${var.name_prefix}-portal-api-5xx"
  alarm_description   = "Portal HTTP API returned a server error."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "5xx"
  namespace           = "AWS/ApiGateway"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = sort(tolist(var.alarm_notification_topic_arns))

  dimensions = {
    ApiId = aws_apigatewayv2_api.portal.id
    Stage = aws_apigatewayv2_stage.portal.name
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-portal-api-5xx" })
}
