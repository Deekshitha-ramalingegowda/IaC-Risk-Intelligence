# Security Group
resource "aws_security_group" "ec2_sg" {
  name        = "${var.instance_name}-sg"
  description = "Security group for ${var.instance_name}"

  tags = merge(var.tags, {
    Name = "${var.instance_name}-sg"
  })
}

# Ingress Rules
resource "aws_security_group_rule" "ingress" {
  count             = length(var.security_group_rules)
  type              = "ingress"
  from_port         = var.security_group_rules[count.index].from_port
  to_port           = var.security_group_rules[count.index].to_port
  protocol          = var.security_group_rules[count.index].protocol
  cidr_blocks       = var.security_group_rules[count.index].cidr_blocks
  security_group_id = aws_security_group.ec2_sg.id
}

# Egress Rule (allow all outbound traffic)
resource "aws_security_group_rule" "egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  security_group_id = aws_security_group.ec2_sg.id
}

# EC2 Instance
resource "aws_instance" "ec2" {
  ami                    = var.ami_id
  instance_type          = var.instance_type
  associate_public_ip_address = var.associate_public_ip
  monitoring             = var.enable_monitoring
  vpc_security_group_ids = [aws_security_group.ec2_sg.id]
 
  iam_instance_profile   = var.iam_instance_profile != null ? var.iam_instance_profile : null
  
  root_block_device {
    volume_type           = var.root_volume_type
    volume_size           = var.root_volume_size
    delete_on_termination = true
    encrypted             = var.enable_encryption
  }

  user_data = var.user_data != null ? base64encode(var.user_data) : null

  tags = merge(var.tags, {
    Name = var.instance_name
  })
}

# Elastic IP (optional)
resource "aws_eip" "ec2_eip" {
  count    = var.attach_eip ? 1 : 0
  instance = aws_instance.ec2.id
  domain   = "vpc"

  tags = merge(var.tags, {
    Name = "${var.instance_name}-eip"
  })
}

# CloudWatch Alarms for monitoring
resource "aws_cloudwatch_metric_alarm" "cpu_utilization" {
  count               = var.enable_monitoring ? 1 : 0
  alarm_name          = "${var.instance_name}-high-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Alert when CPU exceeds 80%"
  dimensions = {
    InstanceId = aws_instance.ec2.id
  }
}
