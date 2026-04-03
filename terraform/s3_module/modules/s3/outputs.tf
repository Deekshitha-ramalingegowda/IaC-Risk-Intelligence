output "bucket_id" {
  description = "Bucket ID"
  value       = aws_s3_bucket.bucket.id
}

output "bucket_arn" {
  description = "Bucket ARN"
  value       = aws_s3_bucket.bucket.arn
}

output "bucket_name" {
  description = "Bucket Name"
  value       = aws_s3_bucket.bucket.bucket
}
