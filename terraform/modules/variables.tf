# ── Shared ───────────────────────────────────────────────────────────────────
variable "tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default     = {}
}

# ── EC2 ──────────────────────────────────────────────────────────────────────
variable "ami" {
  description = "AMI ID for the EC2 instance"
  type        = string
}

variable "ec2_instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m5.2xlarge"   # intentionally oversized for cost issue demo
}

variable "ec2_volume_size" {
  description = "Root EBS volume size in GB"
  type        = number
  default     = 50
}

# ── S3 ───────────────────────────────────────────────────────────────────────
variable "bucket_name" {
  description = "S3 bucket name"
  type        = string
}

# ── VPC ──────────────────────────────────────────────────────────────────────
variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "private_subnets" {
  description = "Map of AZ key to subnet CIDR"
  type        = map(string)
  default = {
    a = "10.0.1.0/24"
    b = "10.0.2.0/24"
  }
}

variable "flow_log_role_arn" {
  description = "IAM role ARN for VPC flow logs"
  type        = string
}

variable "flow_log_destination" {
  description = "CloudWatch log group ARN for VPC flow logs"
  type        = string
}

# ── RDS ──────────────────────────────────────────────────────────────────────
variable "db_engine" {
  description = "RDS database engine"
  type        = string
  default     = "mysql"
}

variable "db_engine_version" {
  description = "RDS engine version"
  type        = string
  default     = "8.0"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.medium"
}

variable "db_allocated_storage" {
  description = "Allocated RDS storage in GB"
  type        = number
  default     = 50
}

variable "db_name" {
  description = "Initial database name"
  type        = string
}

variable "rds_monitoring_role_arn" {
  description = "IAM role ARN for RDS enhanced monitoring"
  type        = string
}

