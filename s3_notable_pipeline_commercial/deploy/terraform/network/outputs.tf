output "lambda_security_group_id" {
  description = "Primary Lambda security group ID for SAM CustomerSecurityGroupIds."
  value       = aws_security_group.lambda.id
}

output "lambda_security_group_ids" {
  description = "Lambda security group IDs created by this module."
  value       = [aws_security_group.lambda.id]
}

output "vpc_id" {
  description = "Customer VPC ID passed through for downstream modules."
  value       = var.vpc_id
}

output "subnet_ids" {
  description = "Private subnet IDs passed through for downstream modules."
  value       = sort(local.private_subnet_ids)
}

output "sam_environment" {
  description = "Values to copy into the customer-default SAM preset."
  value = {
    CUSTOMER_VPC_SUBNET_IDS     = join(",", sort(local.private_subnet_ids))
    CUSTOMER_SECURITY_GROUP_IDS = aws_security_group.lambda.id
  }
}
