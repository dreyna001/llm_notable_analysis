resource "aws_sqs_queue" "analyzer_dlq" {
  name                      = "${var.name_prefix}-analyzer-dlq"
  message_retention_seconds = var.queue_settings.dlq_retention_seconds
  kms_master_key_id         = var.kms_key_arn
  sqs_managed_sse_enabled   = local.kms_enabled ? null : true
  tags                      = local.tags
}

resource "aws_sqs_queue" "analyzer" {
  name                       = "${var.name_prefix}-analyzer-queue"
  visibility_timeout_seconds = var.queue_settings.visibility_timeout_seconds
  message_retention_seconds  = var.queue_settings.message_retention_seconds
  kms_master_key_id          = var.kms_key_arn
  sqs_managed_sse_enabled    = local.kms_enabled ? null : true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.analyzer_dlq.arn
    maxReceiveCount     = var.queue_settings.max_receive_count
  })
  tags = local.tags
}

resource "aws_sqs_queue" "embed_dlq" {
  count = var.features.case_qa ? 1 : 0

  name                      = "${var.name_prefix}-embed-dlq"
  message_retention_seconds = var.queue_settings.dlq_retention_seconds
  kms_master_key_id         = var.kms_key_arn
  sqs_managed_sse_enabled   = local.kms_enabled ? null : true
  tags                      = local.tags
}

resource "aws_sqs_queue" "embed" {
  count = var.features.case_qa ? 1 : 0

  name                       = "${var.name_prefix}-embed-queue"
  visibility_timeout_seconds = var.queue_settings.visibility_timeout_seconds
  message_retention_seconds  = var.queue_settings.message_retention_seconds
  kms_master_key_id          = var.kms_key_arn
  sqs_managed_sse_enabled    = local.kms_enabled ? null : true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.embed_dlq[0].arn
    maxReceiveCount     = var.queue_settings.max_receive_count
  })
  tags = local.tags
}

resource "aws_sqs_queue" "rag_dlq" {
  count = var.features.rag_ingestion ? 1 : 0

  name                      = "${var.name_prefix}-rag-ingestion-dlq"
  message_retention_seconds = var.queue_settings.dlq_retention_seconds
  kms_master_key_id         = var.kms_key_arn
  sqs_managed_sse_enabled   = local.kms_enabled ? null : true
  tags                      = local.tags
}

resource "aws_sqs_queue" "rag" {
  count = var.features.rag_ingestion ? 1 : 0

  name                       = "${var.name_prefix}-rag-ingestion-queue"
  visibility_timeout_seconds = var.queue_settings.visibility_timeout_seconds
  message_retention_seconds  = var.queue_settings.message_retention_seconds
  kms_master_key_id          = var.kms_key_arn
  sqs_managed_sse_enabled    = local.kms_enabled ? null : true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.rag_dlq[0].arn
    maxReceiveCount     = var.queue_settings.max_receive_count
  })
  tags = local.tags
}

data "aws_iam_policy_document" "analyzer_queue_notification" {
  statement {
    sid       = "AllowInputBucketSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.analyzer.arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:s3:::${var.input_bucket_name}"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }

}

resource "aws_sqs_queue_policy" "notifications" {
  queue_url = aws_sqs_queue.analyzer.id
  policy    = data.aws_iam_policy_document.analyzer_queue_notification.json
}

data "aws_iam_policy_document" "rag_queue_notification" {
  count = var.features.rag_ingestion ? 1 : 0

  statement {
    sid       = "AllowRagSourceBucketSend"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.rag[0].arn]

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:s3:::${local.rag_source_bucket}"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sqs_queue_policy" "rag_notifications" {
  count = var.features.rag_ingestion ? 1 : 0

  queue_url = aws_sqs_queue.rag[0].id
  policy    = data.aws_iam_policy_document.rag_queue_notification[0].json
}
