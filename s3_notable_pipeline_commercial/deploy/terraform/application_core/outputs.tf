output "analyzer_function_name" {
  description = "Analyzer Lambda function name."
  value       = aws_lambda_function.analyzer.function_name
}

output "analyzer_function_arn" {
  description = "Analyzer Lambda function ARN."
  value       = aws_lambda_function.analyzer.arn
}

output "analyzer_role_name" {
  description = "Deterministic analyzer IAM role name."
  value       = aws_iam_role.analyzer.name
}

output "analyzer_role_arn" {
  description = "Analyzer IAM role ARN for OpenSearch and KMS policies."
  value       = aws_iam_role.analyzer.arn
}

output "case_embed_function_name" {
  description = "Case embedding Lambda function name, or null when Case Q&A is disabled."
  value       = try(aws_lambda_function.embed[0].function_name, null)
}

output "case_embed_function_arn" {
  description = "Case embedding Lambda function ARN, or null when Case Q&A is disabled."
  value       = try(aws_lambda_function.embed[0].arn, null)
}

output "case_embed_role_name" {
  description = "Case embedding IAM role name, or null when Case Q&A is disabled."
  value       = try(aws_iam_role.embed[0].name, null)
}

output "case_embed_role_arn" {
  description = "Case embedding IAM role ARN for OpenSearch and KMS policies."
  value       = try(aws_iam_role.embed[0].arn, null)
}

output "rag_ingestion_function_name" {
  description = "RAG ingestion Lambda function name, or null when ingestion is disabled."
  value       = try(aws_lambda_function.rag[0].function_name, null)
}

output "rag_ingestion_function_arn" {
  description = "RAG ingestion Lambda function ARN, or null when ingestion is disabled."
  value       = try(aws_lambda_function.rag[0].arn, null)
}

output "rag_ingestion_role_name" {
  description = "RAG ingestion IAM role name, or null when ingestion is disabled."
  value       = try(aws_iam_role.rag[0].name, null)
}

output "rag_ingestion_role_arn" {
  description = "RAG ingestion IAM role ARN for OpenSearch and KMS policies."
  value       = try(aws_iam_role.rag[0].arn, null)
}

output "input_bucket_name" {
  description = "Managed input bucket name."
  value       = aws_s3_bucket.input.bucket
}

output "output_bucket_name" {
  description = "Managed output bucket name."
  value       = aws_s3_bucket.output.bucket
}

output "analyzer_queue_url" {
  description = "Analyzer queue URL."
  value       = aws_sqs_queue.analyzer.id
}

output "analyzer_queue_arn" {
  description = "Analyzer queue ARN."
  value       = aws_sqs_queue.analyzer.arn
}

output "analyzer_dlq_url" {
  description = "Analyzer dead-letter queue URL."
  value       = aws_sqs_queue.analyzer_dlq.id
}

output "case_embed_queue_url" {
  description = "Case embedding queue URL, or null when Case Q&A is disabled."
  value       = try(aws_sqs_queue.embed[0].id, null)
}

output "case_embed_queue_arn" {
  description = "Case embedding queue ARN, or null when Case Q&A is disabled."
  value       = try(aws_sqs_queue.embed[0].arn, null)
}

output "case_embed_dlq_url" {
  description = "Case embedding dead-letter queue URL, or null when Case Q&A is disabled."
  value       = try(aws_sqs_queue.embed_dlq[0].id, null)
}

output "rag_ingestion_queue_arn" {
  description = "RAG ingestion queue ARN for notifications from an external source bucket."
  value       = try(aws_sqs_queue.rag[0].arn, null)
}

output "rag_ingestion_queue_url" {
  description = "RAG ingestion queue URL, or null when ingestion is disabled."
  value       = try(aws_sqs_queue.rag[0].id, null)
}

output "rag_ingestion_dlq_url" {
  description = "RAG ingestion dead-letter queue URL, or null when ingestion is disabled."
  value       = try(aws_sqs_queue.rag_dlq[0].id, null)
}

output "case_index_table_name" {
  description = "Case index table name, or null when Case Q&A is disabled."
  value       = try(aws_dynamodb_table.case_index[0].name, null)
}

output "case_index_table_arn" {
  description = "Case index table ARN, or null when Case Q&A is disabled."
  value       = try(aws_dynamodb_table.case_index[0].arn, null)
}

output "opensearch_read_role_arns" {
  description = "Core role ARNs that need read access in the OpenSearch domain policy."
  value       = [aws_iam_role.analyzer.arn]
}

output "opensearch_write_role_arns" {
  description = "Core role ARNs that need write access in the OpenSearch domain policy."
  value = compact([
    try(aws_iam_role.embed[0].arn, null),
    try(aws_iam_role.rag[0].arn, null),
  ])
}

output "kms_lambda_role_arns" {
  description = "Core Lambda role ARNs for customer KMS key policy wiring."
  value = compact([
    aws_iam_role.analyzer.arn,
    try(aws_iam_role.embed[0].arn, null),
    try(aws_iam_role.rag[0].arn, null),
  ])
}
