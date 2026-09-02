output "kms_key_arn" {
  description = "Customer-managed KMS key ARN for SAM CustomerKmsKeyArn and OpenSearch encrypt_at_rest."
  value       = aws_kms_key.this.arn
}

output "kms_key_id" {
  description = "Customer-managed KMS key ID."
  value       = aws_kms_key.this.key_id
}

output "kms_key_alias" {
  description = "KMS alias bound to the customer-managed key."
  value       = aws_kms_alias.this.name
}

output "sam_environment" {
  description = "Values to copy into the customer-default SAM preset."
  value = {
    CUSTOMER_KMS_KEY_ARN         = aws_kms_key.this.arn
    KMS_PHASE_B_ROLES_APPLIED    = length(var.lambda_role_arns) > 0
    KMS_OPENSEARCH_GRANT_ENABLED = var.enable_opensearch_grant
  }
}
