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

##s3 buckets 

resource "aws_s3_bucket" "bad_bucket1" {
  bucket = "my-insecure-bucket-12345"

  acl = "public-read"   # ❌ public access

  versioning {
    enabled = false     # ❌ versioning disabled
  }

  tags = {
    Environment = "dev"
  }
}

# ❌ No encryption enabled

# ❌ Public access policy
resource "aws_s3_bucket_policy" "public_access" {
  bucket = aws_s3_bucket.bad_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = "*"
        Action = "s3:GetObject"
        Resource = "${aws_s3_bucket.bad_bucket.arn}/*"
      }
    ]
  })
}