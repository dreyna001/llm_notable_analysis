resource "aws_s3_bucket" "input" {
  bucket = var.input_bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "input" {
  bucket = aws_s3_bucket.input.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "input" {
  bucket = aws_s3_bucket.input.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = local.kms_enabled ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = local.kms_enabled
  }
}

resource "aws_s3_bucket_versioning" "input" {
  bucket = aws_s3_bucket.input.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "input" {
  bucket = aws_s3_bucket.input.id

  rule {
    id     = "DeleteIncomingNotablesAfterRetention"
    status = "Enabled"
    filter { prefix = "incoming/" }
    expiration { days = var.retention.input_days }
  }
}

resource "aws_s3_bucket_notification" "input" {
  bucket = aws_s3_bucket.input.id

  queue {
    queue_arn     = aws_sqs_queue.analyzer.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "incoming/"
  }

  dynamic "queue" {
    for_each = var.features.rag_ingestion && var.rag_source_bucket_name == null ? [1] : []
    content {
      queue_arn     = aws_sqs_queue.rag[0].arn
      events        = ["s3:ObjectCreated:*"]
      filter_prefix = var.rag_settings.manifest_prefix
    }
  }

  depends_on = [
    aws_sqs_queue_policy.notifications,
    aws_sqs_queue_policy.rag_notifications,
  ]
}

resource "aws_s3_bucket" "output" {
  bucket = var.output_bucket_name
  tags   = local.tags
}

resource "aws_s3_bucket_public_access_block" "output" {
  bucket = aws_s3_bucket.output.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "output" {
  bucket = aws_s3_bucket.output.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = local.kms_enabled ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = local.kms_enabled
  }
}

resource "aws_s3_bucket_versioning" "output" {
  bucket = aws_s3_bucket.output.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "output" {
  bucket = aws_s3_bucket.output.id

  rule {
    id     = "DeleteOutputReportsAfterRetention"
    status = "Enabled"
    filter { prefix = "reports/" }
    expiration { days = var.retention.output_days }
  }

  dynamic "rule" {
    for_each = var.features.case_archive && var.case_archive_bucket_name == null ? [1] : []
    content {
      id     = "DeleteCaseArchiveAfterRetention"
      status = "Enabled"
      filter { prefix = "${var.case_settings.archive_prefix}/" }
      expiration { days = var.retention.case_days }
    }
  }

  dynamic "rule" {
    for_each = var.features.case_archive && var.case_archive_bucket_name == null ? [1] : []
    content {
      id     = "DeleteCaseChunksAfterRetention"
      status = "Enabled"
      filter { prefix = "${var.case_settings.chunks_prefix}/" }
      expiration { days = var.retention.case_days }
    }
  }
}

resource "aws_dynamodb_table" "case_index" {
  count = var.features.case_qa ? 1 : 0

  name         = var.case_index_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "case_id"

  attribute {
    name = "case_id"
    type = "S"
  }

  attribute {
    name = "archive_partition"
    type = "S"
  }

  attribute {
    name = "processed_at_case_id"
    type = "S"
  }

  attribute {
    name = "correlation_id"
    type = "S"
  }

  global_secondary_index {
    name            = "ProcessedAtIndex"
    projection_type = "ALL"

    key_schema {
      attribute_name = "archive_partition"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "processed_at_case_id"
      key_type       = "RANGE"
    }
  }

  global_secondary_index {
    name            = "CorrelationIdIndex"
    projection_type = "ALL"

    key_schema {
      attribute_name = "correlation_id"
      key_type       = "HASH"
    }

    key_schema {
      attribute_name = "processed_at_case_id"
      key_type       = "RANGE"
    }
  }

  ttl {
    attribute_name = "expires_at_epoch"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = local.tags
}
