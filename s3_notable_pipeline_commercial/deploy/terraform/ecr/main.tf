resource "aws_ecr_repository" "this" {
  name                 = var.repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = var.repository_name
  }

  lifecycle {
    precondition {
      condition     = data.aws_partition.current.partition == "aws"
      error_message = "The commercial ECR stack must run in partition aws."
    }

    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "The commercial ECR stack must run in us-east-1."
    }

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Active AWS account does not match aws_account_id."
    }
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  count      = var.enable_lifecycle_policy ? 1 : 0
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep the last ${var.lifecycle_image_count} images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.lifecycle_image_count
        }
        action = {
          type = "expire"
        }
      },
    ]
  })
}
