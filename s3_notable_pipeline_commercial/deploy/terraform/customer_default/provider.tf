provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge({
      Application = "llm-notable-analysis"
      ManagedBy   = "Terraform"
      Profile     = "customer-default"
    }, var.tags)
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}
