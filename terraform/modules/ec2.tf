resource "aws_instance" "app" {
  ami           = var.ami
  instance_type = "m5.2xlarge"   
  monitoring    = false              

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

