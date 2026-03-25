resource "aws_security_group" "this" {
  name        = "${var.project_name}-sg"
  description = "Allow SSH access"
  vpc_id      = var.vpc_id

  ingress {
    description = "SSH access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"

    # 🔐 Restrict this in production
    cidr_blocks = var.allowed_cidr
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = var.tags
}

resource "aws_instance" "this" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  vpc_security_group_ids = [aws_security_group.this.id]
  key_name               = var.key_name

  # ✅ FIXED: Security Best Practices
  monitoring = true   # CloudWatch detailed monitoring

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"   # IMDSv2 enforced
  }

  root_block_device {
    encrypted = true
    volume_size = 20
  }

  tags = merge(var.tags, {
    Name = "${var.project_name}-ec2"
  })
}