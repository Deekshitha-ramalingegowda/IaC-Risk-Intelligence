module "s3_public_bucket" {
  source = "./modules/s3"

  bucket_name = "my-public-bucket-4567"

  block_public_access = false
  acl                 = "public-read"
  enable_versioning   = true

  attach_policy = true
  policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:ListBucket"]
        Resource  = ["arn:aws:s3:::my-public-bucket-4567", "arn:aws:s3:::my-public-bucket-4567/*"]
      }
    ]
  })

  enable_logging = true
  log_target_bucket = "my-log-bucket"

  tags = {
    Environment = "dev"
  }
}