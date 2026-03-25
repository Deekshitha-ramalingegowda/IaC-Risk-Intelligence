variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_id" {
  type = string
}

variable "ec2_instance_type" {
  type    = string
  default = "m5.2xlarge"
}

variable "ami_id" {
  type = string
}

variable "key_name" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}