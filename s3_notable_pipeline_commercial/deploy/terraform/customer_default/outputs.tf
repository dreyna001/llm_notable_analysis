output "deployment" {
  description = "Non-secret deployment handoff values."
  value = {
    status                  = var.deploy_application ? "application_deployed" : "ecr_bootstrapped"
    ecr_repository_uri      = local.ecr_repository_uri
    immutable_image_uri     = var.deploy_application ? local.image_uri : null
    opensearch_endpoint     = var.deploy_application ? local.opensearch_endpoint : null
    input_bucket_name       = var.deploy_application ? module.application_core[0].input_bucket_name : null
    output_bucket_name      = var.deploy_application ? module.application_core[0].output_bucket_name : null
    analyzer_queue_url      = var.deploy_application ? module.application_core[0].analyzer_queue_url : null
    analyzer_dlq_url        = var.deploy_application ? module.application_core[0].analyzer_dlq_url : null
    case_embed_queue_url    = var.deploy_application ? module.application_core[0].case_embed_queue_url : null
    case_embed_dlq_url      = var.deploy_application ? module.application_core[0].case_embed_dlq_url : null
    rag_ingestion_queue_url = var.deploy_application ? module.application_core[0].rag_ingestion_queue_url : null
    rag_ingestion_dlq_url   = var.deploy_application ? module.application_core[0].rag_ingestion_dlq_url : null
    portal_ui_bucket_name   = var.deploy_application ? module.application_portal[0].portal_ui_bucket_name : null
    portal_api_url          = var.deploy_application ? module.application_portal[0].portal_api_url : null
    application_role_arns   = var.deploy_application ? local.role_arns : null
  }
}

output "ecr_repository_uri" {
  description = "ECR repository URI used by the image build step."
  value       = local.ecr_repository_uri
}
