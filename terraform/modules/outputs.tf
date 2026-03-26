# ── EC2 ──────────────────────────────────────────────────────────────────────
output "ec2_instance_id" {
  description = "ID of the EC2 instance"
  value       = aws_instance.app.id
}

output "ec2_private_ip" {
  description = "Private IP of the EC2 instance"
  value       = aws_instance.app.private_ip
}

# ── S3 ───────────────────────────────────────────────────────────────────────
output "s3_bucket_id" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.app.id
}

output "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.app.arn
}

# ── VPC ──────────────────────────────────────────────────────────────────────
output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.app.id
}

output "private_subnet_ids" {
  description = "Map of private subnet IDs"
  value       = { for k, s in aws_subnet.private : k => s.id }
}

# ── RDS ──────────────────────────────────────────────────────────────────────
output "rds_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.app.endpoint
}

output "rds_instance_id" {
  description = "RDS instance identifier"
  value       = aws_db_instance.app.id
}

