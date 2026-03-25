variable "region" {
  default = "ap-south-1"
}

variable "project_name" {
  default = "demo"
}

variable "vpc_cidr" {
  default = "10.0.0.0/16"
}

variable "subnet_cidr" {
  default = "10.0.1.0/24"
}

variable "az" {
  default = "ap-south-1a"
}

variable "ami_id" {
  default = "ami-0f58b397bc5c1f2e8"
}

variable "instance_type" {
  default = "t3.micro"
}

variable "key_name" {
  description = "EC2 Key Pair name for SSH access"
  default     = "your-key-name"
  type        = string
}

variable "allowed_ip" {
  description = "⚠️ SECURITY: Restrict SSH access to your trusted IP/CIDR. DO NOT leave as 0.0.0.0/0 in production. Example: '203.0.113.0/24'"
  default     = "0.0.0.0/0" # CHANGE THIS to your office IP or VPN CIDR
  type        = string
}