resource "aws_vpc" "app" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  tags                 = var.tags
}

resource "aws_subnet" "private" {
  for_each                = var.private_subnets
  vpc_id                  = aws_vpc.app.id
  cidr_block              = each.value
  map_public_ip_on_launch = false
  tags                    = var.tags
}

resource "aws_flow_log" "app" {
  vpc_id          = aws_vpc.app.id
  traffic_type    = "ALL"
  iam_role_arn    = var.flow_log_role_arn
  log_destination = var.flow_log_destination
}

resource "aws_default_security_group" "app" {
  vpc_id  = aws_vpc.app.id
  ingress = []
  egress  = []
}

