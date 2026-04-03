module "s3_public_bucket" {
  source = "./modules/s3"

  bucket_name = "my-public-bucket-4567"

  block_public_access = false
  acl                 = "public-read"

  attach_policy = true
  policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "arn:aws:s3:::my-public-bucket-12345/*"
      }
    ]
  })

  tags = {
    Environment = "dev"
  }
}
