output "opensearch_endpoint" {
  description = "HTTPS endpoint for the SAM OpenSearchEndpoint parameter."
  value       = "https://${aws_opensearch_domain.this.endpoint}"
}

output "opensearch_domain_arn" {
  description = "Domain ARN for the SAM OpenSearchDomainArn parameter."
  value       = aws_opensearch_domain.this.arn
}

output "opensearch_security_group_id" {
  description = "Security group attached to the VPC-only OpenSearch domain."
  value       = aws_security_group.opensearch.id
}

output "domain_name" {
  description = "Created OpenSearch domain name."
  value       = aws_opensearch_domain.this.domain_name
}

output "sam_environment" {
  description = "Values to copy into the customer-default SAM preset."
  value = {
    OPENSEARCH_ENDPOINT              = "https://${aws_opensearch_domain.this.endpoint}"
    OPENSEARCH_DOMAIN_ARN            = aws_opensearch_domain.this.arn
    CUSTOMER_VPC_SUBNET_IDS          = join(",", sort(tolist(var.subnet_ids)))
    CUSTOMER_SECURITY_GROUP_IDS      = join(",", sort(tolist(var.lambda_security_group_ids)))
    CUSTOMER_KMS_KEY_ARN             = var.kms_key_arn == null ? "" : var.kms_key_arn
    OPENSEARCH_SECURITY_GROUP_ID     = aws_security_group.opensearch.id
    OPENSEARCH_PHASE_B_ROLES_APPLIED = length(var.read_role_arns) + length(var.write_role_arns) > 0
  }
}
