variable "region" {}
variable "project_name" {}

variable "vpc_cidr" {}
variable "public_subnet_cidr" {}
variable "az" {}

variable "ami_id" {}
variable "instance_type" {}
variable "key_name" {}

variable "tags" {
  type = map(string)
}