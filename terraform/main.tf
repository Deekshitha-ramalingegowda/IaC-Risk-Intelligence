provider "aws" {
  region = "us-east-1"
}
 
resource "aws_instance" "app" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "m5.2xlarge"
  monitoring    = false
 
  root_block_device {
    volume_type = "gp2"
    volume_size = 500
    encrypted   = false
  }
 
  tags = {
    Name = "app-server"
  }
}
 

 resource "aws_s3_bucket" "bad_bucket" {
  bucket = "my-insecure-bucket-12345"

  force_destroy = true
}

resource "aws_s3_bucket" "logs_bucket" {
  bucket = "my-logs-bucket-12345"

  force_destroy = true
}

# ❌ Public access completely open
resource "aws_s3_bucket_public_access_block" "logs_block" {
  bucket = aws_s3_bucket.logs_bucket.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# ❌ Public read access
resource "aws_s3_bucket_acl" "logs_acl" {
  bucket = aws_s3_bucket.logs_bucket.id
  acl    = "public-read"
}

# ❌ Open bucket policy (CRITICAL)
resource "aws_s3_bucket_policy" "logs_policy" {
  bucket = aws_s3_bucket.logs_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = "s3:GetObject"
        Resource = "${aws_s3_bucket.logs_bucket.arn}/*"
      }
    ]
  })
}

# ❌ Faulty lifecycle configuration
resource "aws_s3_bucket_lifecycle_configuration" "logs_lifecycle" {
  bucket = aws_s3_bucket.logs_bucket.id

  rule {
    id     = "log-retention"
    status = "Enabled"

    # ❌ Deletes too early (data loss)
    expiration {
      days = 1
    }

    # ❌ Bad cost transitions
    transition {
      days          = 1
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 2
      storage_class = "GLACIER"
    }

    # ❌ No filter → applies to entire bucket
  }
}