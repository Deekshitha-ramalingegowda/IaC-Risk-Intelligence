output "instance_id" {
  description = "EC2 Instance ID"
  value       = aws_instance.ec2.id
}

output "instance_arn" {
  description = "EC2 Instance ARN"
  value       = aws_instance.ec2.arn
}

output "public_ip" {
  description = "Public IP address of the instance"
  value       = aws_instance.ec2.public_ip
}

output "private_ip" {
  description = "Private IP address of the instance"
  value       = aws_instance.ec2.private_ip
}

output "security_group_id" {
  description = "Security Group ID"
  value       = aws_security_group.ec2_sg.id
}

output "security_group_name" {
  description = "Security Group Name"
  value       = aws_security_group.ec2_sg.name
}

output "eip_id" {
  description = "Elastic IP ID"
  value       = try(aws_eip.ec2_eip[0].id, null)
}

output "eip_address" {
  description = "Elastic IP Address"
  value       = try(aws_eip.ec2_eip[0].public_ip, null)
}
