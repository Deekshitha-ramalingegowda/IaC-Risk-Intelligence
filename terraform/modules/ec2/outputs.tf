output "instance_id"       { value = aws_instance.main.id }
output "private_ip"        { value = aws_instance.main.private_ip }
output "security_group_id" { value = aws_security_group.ec2.id }


