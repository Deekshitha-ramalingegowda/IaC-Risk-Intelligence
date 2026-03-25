variable "project_name" {}
variable "vpc_cidr" {}
variable "public_subnet_cidr" {}
variable "az" {}
variable "tags" {
  type = map(string)
}