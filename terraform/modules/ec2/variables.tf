variable "project_name" {}
variable "vpc_id" {}
variable "subnet_id" {}
variable "ami_id" {}

variable "instance_type" {
  default = "t3.micro"
}

variable "key_name" {
  default = null
}

variable "allowed_cidr" {
  type    = list(string)
  default = ["0.0.0.0/0"] # ⚠ restrict in prod
}

variable "tags" {
  type = map(string)
}