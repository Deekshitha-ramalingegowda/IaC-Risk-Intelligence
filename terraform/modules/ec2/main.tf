# ── Security Group ────────────────────────────────────────────────────────────
resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2-sg"
  description = "Security group for ${var.project_name} EC2 instance"
  vpc_id      = var.vpc_id

  # SECURITY (CKV_AWS_25): SSH open to world
  ingress {
    description = "SSH from anywhere"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]   # triggers CKV_AWS_25
  }

  # SECURITY (CKV_AWS_260): HTTP open to world
  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SECURITY (CKV_AWS_277): Unrestricted egress
  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.project_name}-ec2-sg" })
}

# ── EC2 Instance ──────────────────────────────────────────────────────────────
resource "aws_instance" "main" {
  ami           = var.ami_id
  instance_type = var.ec2_instance_type   # default m5.2xlarge → ~$277/mo
  subnet_id     = var.subnet_id

  # [CKV_AWS_126] Detailed CloudWatch monitoring disabled — fix: monitoring = true
  monitoring = false

  # [CKV_AWS_8] IMDSv2 not enforced — fix: http_tokens = "required"
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "optional"
    http_put_response_hop_limit = 1
  }

  # [CKV_AWS_135] Root volume not encrypted — fix: encrypted = true
  root_block_device {
    volume_type           = "gp3"
    volume_size           = 30
    encrypted             = false
    delete_on_termination = true
  }

  # [CKV_AWS_135] Data volume not encrypted
  ebs_block_device {
    device_name           = "/dev/xvdb"
    volume_type           = "gp3"
    volume_size           = 100
    encrypted             = false
    delete_on_termination = false
  }

  vpc_security_group_ids = [aws_security_group.ec2.id]
  key_name               = var.key_name != "" ? var.key_name : null

  # [CKV2_AWS_41] No IAM instance profile — intentionally omitted

  tags = merge(var.tags, { Name = "${var.project_name}-instance" })
}