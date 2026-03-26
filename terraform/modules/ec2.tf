resource "aws_instance" "app" {
  ami           = var.ami
  instance_type = var.ec2_instance_type   # COST: m5.2xlarge is oversized (~$277/mo)
  monitoring    = false                   # SECURITY: detailed monitoring disabled (CKV_AWS_126)

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = var.ec2_volume_size
    encrypted   = true
  }

  tags = var.tags
}

