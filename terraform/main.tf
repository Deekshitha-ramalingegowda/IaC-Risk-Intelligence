provider "aws" {
  region = "us-east-1"
}

resource "aws_instance" "app" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.large"
  monitoring    = false

  root_block_device {
    volume_type = "gp2"
    volume_size = 500
    encrypted   = false
  }


  tags = {
    Environment = var.environment
    Project     = var.project_name
    ManagedBy   = "terraform"
  }

  # ec2
  ami               = var.ami
  ec2_instance_type = var.ec2_instance_type
  ec2_volume_size   = var.ec2_volume_size

  # s3
  bucket_name = var.bucket_name

  # vpc
  vpc_cidr             = var.vpc_cidr
  private_subnets      = var.private_subnets
  flow_log_role_arn    = var.flow_log_role_arn
  flow_log_destination = var.flow_log_destination

  # rds
  db_engine               = var.db_engine
  db_engine_version       = var.db_engine_version
  db_instance_class       = var.db_instance_class
  db_allocated_storage    = var.db_allocated_storage
  db_name                 = var.db_name
  rds_monitoring_role_arn = var.rds_monitoring_role_arn
}

