variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "demo"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  type    = string
  default = "10.0.1.0/24"
}

variable "private_subnet_cidr" {
  type    = string
  default = "10.0.2.0/24"
}

variable "availability_zone" {
  type    = string
  default = "us-east-1a"
}

# COST ALERT: m5.2xlarge ~$277/mo. Use m5.large (~$70) for non-prod.
variable "ec2_instance_type" {
  type    = string
  default = "m5.2xlarge"
}

variable "ami_id" {
  type    = string
  default = "ami-0c02fb55956c7d316"  # Amazon Linux 2 us-east-1
}

variable "key_name" {
  type    = string
  default = ""
}

variable "tags" {
  type = map(string)
  default = {
    Environment = "dev"
    ManagedBy   = "terraform"
  }
}