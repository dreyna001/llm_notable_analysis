locals {
  private_subnet_ids = distinct(var.private_subnet_ids)
  subnet_azs         = toset([for subnet in data.aws_subnet.selected : subnet.availability_zone])

  create_interface_endpoints = (
    var.create_sqs_interface_endpoint ||
    var.create_logs_interface_endpoint ||
    var.create_bedrock_runtime_interface_endpoint ||
    var.create_secretsmanager_interface_endpoint
  )

  interface_endpoint_services = {
    sqs             = var.create_sqs_interface_endpoint
    logs            = var.create_logs_interface_endpoint
    bedrock-runtime = var.create_bedrock_runtime_interface_endpoint
    secretsmanager  = var.create_secretsmanager_interface_endpoint
  }

  enabled_interface_endpoints = {
    for service, enabled in local.interface_endpoint_services : service => enabled if enabled
  }

  interface_endpoint_service_names = {
    sqs             = "com.amazonaws.${data.aws_region.current.region}.sqs"
    logs            = "com.amazonaws.${data.aws_region.current.region}.logs"
    bedrock-runtime = "com.amazonaws.${data.aws_region.current.region}.bedrock-runtime"
    secretsmanager  = "com.amazonaws.${data.aws_region.current.region}.secretsmanager"
  }
}

data "aws_subnet" "selected" {
  for_each = toset(local.private_subnet_ids)
  id       = each.value
}

data "aws_route_tables" "private" {
  vpc_id = var.vpc_id

  filter {
    name   = "association.subnet-id"
    values = local.private_subnet_ids
  }
}

resource "aws_security_group" "lambda" {
  name_prefix = "${var.name_prefix}-lambda-"
  description = "Product Lambda ENIs in customer VPC; egress HTTPS via NAT gateway or VPC endpoints"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name_prefix}-lambda"
  }

  lifecycle {
    create_before_destroy = true

    precondition {
      condition     = data.aws_partition.current.partition == "aws"
      error_message = "The commercial network stack must run in partition aws."
    }

    precondition {
      condition     = data.aws_region.current.region == "us-east-1"
      error_message = "The commercial network stack must run in us-east-1."
    }

    precondition {
      condition     = data.aws_caller_identity.current.account_id == var.aws_account_id
      error_message = "Active AWS account does not match aws_account_id."
    }

    precondition {
      condition     = alltrue([for subnet in data.aws_subnet.selected : subnet.vpc_id == var.vpc_id])
      error_message = "Every private_subnet_id must belong to vpc_id."
    }

    precondition {
      condition     = length(local.subnet_azs) == length(local.private_subnet_ids)
      error_message = "Provide no more than one private subnet per Availability Zone."
    }
  }
}

resource "aws_vpc_security_group_egress_rule" "lambda_https" {
  security_group_id = aws_security_group.lambda.id
  cidr_ipv4         = "0.0.0.0/0"
  description       = "HTTPS to AWS APIs via NAT gateway or VPC interface endpoints; customer routes private subnets accordingly"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_security_group" "vpc_endpoints" {
  count = local.create_interface_endpoints ? 1 : 0

  name_prefix = "${var.name_prefix}-vpc-endpoints-"
  description = "Interface VPC endpoints for product Lambda HTTPS egress"
  vpc_id      = var.vpc_id

  tags = {
    Name = "${var.name_prefix}-vpc-endpoints"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_vpc_security_group_ingress_rule" "endpoint_https_from_lambda" {
  count = local.create_interface_endpoints ? 1 : 0

  security_group_id            = aws_security_group.vpc_endpoints[0].id
  referenced_security_group_id = aws_security_group.lambda.id
  description                  = "HTTPS from product Lambda security group"
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_endpoint" "s3_gateway" {
  count = var.create_s3_gateway_endpoint ? 1 : 0

  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.private.ids

  tags = {
    Name = "${var.name_prefix}-s3-gateway"
  }

  lifecycle {
    precondition {
      condition     = length(data.aws_route_tables.private.ids) > 0
      error_message = "S3 gateway endpoint requires route tables associated with private_subnet_ids."
    }
  }
}

resource "aws_vpc_endpoint" "dynamodb_gateway" {
  count = var.create_dynamodb_gateway_endpoint ? 1 : 0

  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = data.aws_route_tables.private.ids

  tags = {
    Name = "${var.name_prefix}-dynamodb-gateway"
  }

  lifecycle {
    precondition {
      condition     = length(data.aws_route_tables.private.ids) > 0
      error_message = "DynamoDB gateway endpoint requires route tables associated with private_subnet_ids."
    }
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each = local.enabled_interface_endpoints

  vpc_id              = var.vpc_id
  service_name        = local.interface_endpoint_service_names[each.key]
  vpc_endpoint_type   = "Interface"
  subnet_ids          = sort(local.private_subnet_ids)
  security_group_ids  = [aws_security_group.vpc_endpoints[0].id]
  private_dns_enabled = true

  tags = {
    Name = "${var.name_prefix}-${each.key}-interface"
  }
}
