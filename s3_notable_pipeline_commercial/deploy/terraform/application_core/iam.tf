locals {
  lambda_assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "sts:AssumeRole"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  vpc_statement = local.vpc_enabled ? [{
    Sid    = "ManageVpcNetworkInterfaces"
    Effect = "Allow"
    Action = [
      "ec2:CreateNetworkInterface",
      "ec2:DescribeNetworkInterfaces",
      "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses",
      "ec2:UnassignPrivateIpAddresses",
    ]
    Resource = "*"
  }] : []

  kms_write_statement = local.kms_enabled ? [{
    Sid    = "UseCustomerKmsKey"
    Effect = "Allow"
    Action = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:ReEncryptFrom",
      "kms:ReEncryptTo",
    ]
    Resource = var.kms_key_arn
  }] : []

  kms_read_statement = local.kms_enabled ? [{
    Sid      = "ReadWithCustomerKmsKey"
    Effect   = "Allow"
    Action   = ["kms:Decrypt", "kms:DescribeKey"]
    Resource = var.kms_key_arn
  }] : []

  xray_statement = [{
    Sid      = "PublishXRayTelemetry"
    Effect   = "Allow"
    Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
    Resource = "*"
  }]

  analyzer_policy_statements = concat([
    {
      Sid      = "ConsumeAnalyzerQueue"
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = aws_sqs_queue.analyzer.arn
    },
    {
      Sid      = "ReadInputNotables"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "${aws_s3_bucket.input.arn}/*"
    },
    {
      Sid      = "ListInputBucket"
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = aws_s3_bucket.input.arn
    },
    {
      Sid      = "WriteOutputReports"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "${aws_s3_bucket.output.arn}/reports/*"
    },
    {
      Sid      = "InvokeAnalysisModel"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = var.bedrock_analysis_model_arn
    },
    {
      Sid      = "WriteAnalyzerLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.analyzer.arn}:*"
    }
    ], var.features.case_archive ? [{
      Sid      = "WriteCaseArchive"
      Effect   = "Allow"
      Action   = ["s3:PutObject"]
      Resource = "arn:${local.partition}:s3:::${local.archive_bucket_name}/${var.case_settings.archive_prefix}/*"
    }] : [], var.features.case_qa ? [
    {
      Sid      = "UseCaseIndex"
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:UpdateItem"]
      Resource = aws_dynamodb_table.case_index[0].arn
    },
    {
      Sid      = "QueueCaseEmbedding"
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.embed[0].arn
    },
    {
      Sid      = "InvokeEmbeddingModel"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.case_settings.embedding_model}"
    }
    ] : [], var.features.rag ? [{
      Sid      = "ReadOpenSearchKnowledge"
      Effect   = "Allow"
      Action   = ["es:ESHttpGet", "es:ESHttpPost"]
      Resource = "${var.opensearch_domain_arn}/*"
      }] : [], length(var.bedrock_inference_profile_model_arns) > 0 ? [{
      Sid      = "InvokeInferenceProfileModels"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = var.bedrock_inference_profile_model_arns
      Condition = {
        StringEquals = {
          "bedrock:InferenceProfileArn" = var.bedrock_analysis_model_arn
        }
      }
  }] : [], local.vpc_statement, local.kms_write_statement, local.xray_statement)

  embed_policy_statements = concat([
    {
      Sid      = "ConsumeEmbedQueue"
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = var.features.case_qa ? aws_sqs_queue.embed[0].arn : "*"
    },
    {
      Sid    = "ManageCaseArchiveObjects"
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = [
        "arn:${local.partition}:s3:::${local.archive_bucket_name}/${var.case_settings.archive_prefix}/*",
        "arn:${local.partition}:s3:::${local.archive_bucket_name}/${var.case_settings.chunks_prefix}/*",
      ]
    },
    {
      Sid      = "ListCaseArchiveBucket"
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = "arn:${local.partition}:s3:::${local.archive_bucket_name}"
    },
    {
      Sid      = "UpdateCaseIndex"
      Effect   = "Allow"
      Action   = ["dynamodb:UpdateItem"]
      Resource = var.features.case_qa ? aws_dynamodb_table.case_index[0].arn : "*"
    },
    {
      Sid      = "InvokeEmbeddingModel"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.case_settings.embedding_model}"
    },
    {
      Sid      = "WriteEmbedLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = var.features.case_qa ? "${aws_cloudwatch_log_group.embed[0].arn}:*" : "*"
    },
    {
      Sid      = "WriteCaseChunksToOpenSearch"
      Effect   = "Allow"
      Action   = ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"]
      Resource = "${var.opensearch_domain_arn}/*"
    }
  ], local.vpc_statement, local.kms_write_statement, local.xray_statement)

  rag_policy_statements = concat([
    {
      Sid      = "ConsumeRagIngestionQueue"
      Effect   = "Allow"
      Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
      Resource = var.features.rag_ingestion ? aws_sqs_queue.rag[0].arn : "*"
    },
    {
      Sid      = "ReadRagSourceObjects"
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "arn:${local.partition}:s3:::${local.rag_source_bucket}/${var.rag_settings.source_prefix}*"
    },
    {
      Sid      = "ListRagSourceBucket"
      Effect   = "Allow"
      Action   = ["s3:ListBucket"]
      Resource = "arn:${local.partition}:s3:::${local.rag_source_bucket}"
      Condition = {
        StringLike = {
          "s3:prefix" = [var.rag_settings.source_prefix, "${var.rag_settings.source_prefix}*"]
        }
      }
    },
    {
      Sid      = "InvokeEmbeddingModel"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel"]
      Resource = "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.case_settings.embedding_model}"
    },
    {
      Sid      = "ExtractDocumentText"
      Effect   = "Allow"
      Action   = ["textract:DetectDocumentText"]
      Resource = "*"
    },
    {
      Sid      = "WriteKnowledgeToOpenSearch"
      Effect   = "Allow"
      Action   = ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete"]
      Resource = "${var.opensearch_domain_arn}/*"
    },
    {
      Sid      = "WriteRagLogs"
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = var.features.rag_ingestion ? "${aws_cloudwatch_log_group.rag[0].arn}:*" : "*"
    }
  ], local.vpc_statement, local.kms_read_statement, local.xray_statement)
}

resource "aws_iam_role" "analyzer" {
  name               = local.analyzer_role_name
  assume_role_policy = local.lambda_assume_role_policy
  tags               = local.tags
}

resource "aws_iam_role_policy" "analyzer" {
  name = "${var.name_prefix}-analyzer-policy"
  role = aws_iam_role.analyzer.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.analyzer_policy_statements
  })
}

resource "aws_iam_role" "embed" {
  count = var.features.case_qa ? 1 : 0

  name               = local.embed_role_name
  assume_role_policy = local.lambda_assume_role_policy
  tags               = local.tags
}

resource "aws_iam_role_policy" "embed" {
  count = var.features.case_qa ? 1 : 0

  name = "${var.name_prefix}-case-embed-policy"
  role = aws_iam_role.embed[0].id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.embed_policy_statements
  })
}

resource "aws_iam_role" "rag" {
  count = var.features.rag_ingestion ? 1 : 0

  name               = local.rag_role_name
  assume_role_policy = local.lambda_assume_role_policy
  tags               = local.tags
}

resource "aws_iam_role_policy" "rag" {
  count = var.features.rag_ingestion ? 1 : 0

  name = "${var.name_prefix}-rag-ingestion-policy"
  role = aws_iam_role.rag[0].id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.rag_policy_statements
  })
}
