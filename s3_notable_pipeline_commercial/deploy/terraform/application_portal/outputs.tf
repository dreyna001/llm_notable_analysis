output "portal_lambda_function_name" {
  description = "Portal Lambda function name."
  value       = aws_lambda_function.portal.function_name
}

output "portal_lambda_function_arn" {
  description = "Portal Lambda function ARN."
  value       = aws_lambda_function.portal.arn
}

output "portal_lambda_role_name" {
  description = "Deterministic portal Lambda IAM role name."
  value       = aws_iam_role.portal.name
}

output "portal_lambda_role_arn" {
  description = "Portal Lambda IAM role ARN for OpenSearch and KMS access policies."
  value       = aws_iam_role.portal.arn
}

output "case_index_table_name" {
  description = "CaseIndex DynamoDB table name consumed from the core module."
  value       = var.case_index_table_name
}

output "case_index_table_arn" {
  description = "CaseIndex DynamoDB table ARN consumed from the core module."
  value       = var.case_index_table_arn
}

output "chat_sessions_table_name" {
  description = "Chat sessions table name, or null when history is disabled."
  value       = var.chat_history_enabled ? aws_dynamodb_table.chat_sessions[0].name : null
}

output "chat_messages_table_name" {
  description = "Chat messages table name, or null when history is disabled."
  value       = var.chat_history_enabled ? aws_dynamodb_table.chat_messages[0].name : null
}

output "portal_ui_bucket_name" {
  description = "Private portal SPA bucket name."
  value       = aws_s3_bucket.portal_ui.id
}

output "portal_api_id" {
  description = "API Gateway HTTP API ID."
  value       = aws_apigatewayv2_api.portal.id
}

output "portal_api_url" {
  description = "Portal API and browser base URL."
  value       = aws_apigatewayv2_api.portal.api_endpoint
}
