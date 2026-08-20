variable "aws_account_id" {
  description = "Approved 12-digit commercial AWS account ID."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "aws_account_id must be a 12-digit AWS account ID."
  }
}

variable "aws_region" {
  description = "Commercial AWS deployment region. This product supports us-east-1 only."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "aws_region must be us-east-1 for the commercial product."
  }
}

variable "repository_name" {
  description = "ECR repository name for the commercial Lambda image."
  type        = string
  default     = "notable-analyzer-s3"

  validation {
    condition = can(regex(
      "^[a-z][a-z0-9._/-]{1,255}$",
      var.repository_name,
    ))
    error_message = "repository_name must be 2-256 lowercase characters, start with a letter, and contain only letters, digits, hyphens, underscores, periods, or forward slashes."
  }
}

variable "enable_lifecycle_policy" {
  description = "Apply a lifecycle policy that expires images beyond the retention count."
  type        = bool
  default     = true
}

variable "lifecycle_image_count" {
  description = "Number of images to retain when enable_lifecycle_policy is true."
  type        = number
  default     = 30

  validation {
    condition     = var.lifecycle_image_count >= 1
    error_message = "lifecycle_image_count must be at least 1."
  }
}

variable "tags" {
  description = "Additional customer tags applied through the AWS provider."
  type        = map(string)
  default     = {}
}
