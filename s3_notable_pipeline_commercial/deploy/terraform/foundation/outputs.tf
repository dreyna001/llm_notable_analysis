output "sam_environment" {
  description = "Merged SAM preset values from enabled foundation modules."
  value = merge(
    var.enable_kms ? module.kms[0].sam_environment : {},
    var.enable_network ? module.network[0].sam_environment : {
      CUSTOMER_VPC_SUBNET_IDS     = join(",", local.subnet_ids)
      CUSTOMER_SECURITY_GROUP_IDS = join(",", sort(tolist(local.lambda_security_group_ids)))
    },
    var.enable_ecr ? module.ecr[0].sam_environment : {},
    var.enable_opensearch ? module.opensearch[0].sam_environment : {},
  )
}

output "kms_key_arn" {
  description = "Customer KMS key ARN when enable_kms=true."
  value       = var.enable_kms ? module.kms[0].kms_key_arn : local.kms_key_arn
}

output "ecr_repository_uri" {
  description = "ECR repository URI when enable_ecr=true."
  value       = var.enable_ecr ? module.ecr[0].ecr_repository_uri : null
}

output "opensearch_endpoint" {
  description = "OpenSearch HTTPS endpoint when enable_opensearch=true."
  value       = var.enable_opensearch ? module.opensearch[0].opensearch_endpoint : null
}

output "opensearch_domain_arn" {
  description = "OpenSearch domain ARN when enable_opensearch=true."
  value       = var.enable_opensearch ? module.opensearch[0].opensearch_domain_arn : null
}

output "lambda_security_group_id" {
  description = "Lambda security group ID from network module when enabled."
  value       = var.enable_network ? module.network[0].lambda_security_group_id : null
}
