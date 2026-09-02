# Commercial AWS customer-default Terraform root

This is the sole Path B deployment root. It creates or wires ECR, KMS, OpenSearch, the core application, and the analyst portal. SAM is not used.

Terraform 1.10 or newer is required for S3-native state locking.

Copy `backend.hcl.example` to the ignored `backend.hcl` and set the approved remote state bucket and key. Run `scripts/configure_path_b.py`, bootstrap ECR when needed, push the immutable image, then use `scripts/setup-and-deploy.sh` or `.ps1` to plan and apply.

Do not commit `terraform.tfvars`, saved plans, or state files.
