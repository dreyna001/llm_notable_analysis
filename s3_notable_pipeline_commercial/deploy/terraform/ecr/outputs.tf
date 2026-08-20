output "ecr_repository_uri" {
  description = "Commercial ECR repository URI without a tag or digest."
  value       = aws_ecr_repository.this.repository_url
}

output "ecr_repository_arn" {
  description = "ECR repository ARN."
  value       = aws_ecr_repository.this.arn
}

output "repository_name" {
  description = "Created ECR repository name."
  value       = aws_ecr_repository.this.name
}

output "sam_environment" {
  description = "Values to copy into the customer-default SAM preset."
  value = {
    ECR_REPOSITORY_URI = aws_ecr_repository.this.repository_url
  }
}
