locals {
  core_alarms = merge({
    analyzer_queue_depth = {
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateNumberOfMessagesVisible"
      dimension_name      = "QueueName"
      dimension_value     = aws_sqs_queue.analyzer.name
      statistic           = "Maximum"
      evaluation_periods  = 1
      threshold           = 1
      comparison_operator = "GreaterThanOrEqualToThreshold"
    }
    analyzer_dlq = {
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateNumberOfMessagesVisible"
      dimension_name      = "QueueName"
      dimension_value     = aws_sqs_queue.analyzer_dlq.name
      statistic           = "Maximum"
      evaluation_periods  = 1
      threshold           = 0
      comparison_operator = "GreaterThanThreshold"
    }
    analyzer_oldest_message = {
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateAgeOfOldestMessage"
      dimension_name      = "QueueName"
      dimension_value     = aws_sqs_queue.analyzer.name
      statistic           = "Maximum"
      evaluation_periods  = 2
      threshold           = 300
      comparison_operator = "GreaterThanThreshold"
    }
    analyzer_errors = {
      namespace           = "AWS/Lambda"
      metric_name         = "Errors"
      dimension_name      = "FunctionName"
      dimension_value     = aws_lambda_function.analyzer.function_name
      statistic           = "Sum"
      evaluation_periods  = 1
      threshold           = 1
      comparison_operator = "GreaterThanOrEqualToThreshold"
    }
    }, var.features.case_qa ? {
    embed_dlq = {
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateNumberOfMessagesVisible"
      dimension_name      = "QueueName"
      dimension_value     = aws_sqs_queue.embed_dlq[0].name
      statistic           = "Maximum"
      evaluation_periods  = 1
      threshold           = 0
      comparison_operator = "GreaterThanThreshold"
    }
    embed_errors = {
      namespace           = "AWS/Lambda"
      metric_name         = "Errors"
      dimension_name      = "FunctionName"
      dimension_value     = aws_lambda_function.embed[0].function_name
      statistic           = "Sum"
      evaluation_periods  = 1
      threshold           = 1
      comparison_operator = "GreaterThanOrEqualToThreshold"
    }
    } : {}, var.features.rag_ingestion ? {
    rag_oldest_message = {
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateAgeOfOldestMessage"
      dimension_name      = "QueueName"
      dimension_value     = aws_sqs_queue.rag[0].name
      statistic           = "Maximum"
      evaluation_periods  = 2
      threshold           = 300
      comparison_operator = "GreaterThanThreshold"
    }
    rag_dlq = {
      namespace           = "AWS/SQS"
      metric_name         = "ApproximateNumberOfMessagesVisible"
      dimension_name      = "QueueName"
      dimension_value     = aws_sqs_queue.rag_dlq[0].name
      statistic           = "Maximum"
      evaluation_periods  = 1
      threshold           = 0
      comparison_operator = "GreaterThanThreshold"
    }
    rag_errors = {
      namespace           = "AWS/Lambda"
      metric_name         = "Errors"
      dimension_name      = "FunctionName"
      dimension_value     = aws_lambda_function.rag[0].function_name
      statistic           = "Sum"
      evaluation_periods  = 1
      threshold           = 1
      comparison_operator = "GreaterThanOrEqualToThreshold"
    }
  } : {})
}

resource "aws_cloudwatch_metric_alarm" "core" {
  for_each = local.core_alarms

  alarm_name          = "${var.name_prefix}-${replace(each.key, "_", "-")}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric_name
  statistic           = each.value.statistic
  period              = 60
  evaluation_periods  = each.value.evaluation_periods
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison_operator
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions
  dimensions = {
    (each.value.dimension_name) = each.value.dimension_value
  }
  tags = local.tags
}
