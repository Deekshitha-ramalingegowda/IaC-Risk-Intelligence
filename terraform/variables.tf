variable "aws_region"   { default = "us-east-1" }
variable "environment"  { default = "production" }
variable "project_name" { default = "my-app" }

variable "ami"               { type = string }
variable "ec2_instance_type" { default = "m5.2xlarge" }
variable "ec2_volume_size"   { default = 50 }

variable "bucket_name" { type = string }

variable "vpc_cidr"             { default = "10.0.0.0/16" }
variable "private_subnets"      { type = map(string) }
variable "flow_log_role_arn"    { type = string }
variable "flow_log_destination" { type = string }

variable "db_engine"              { default = "mysql" }
variable "db_engine_version"      { default = "8.0" }
variable "db_instance_class"      { default = "db.t3.medium" }
variable "db_allocated_storage"   { default = 50 }
variable "db_name"                { type = string }
variable "rds_monitoring_role_arn" { type = string }



