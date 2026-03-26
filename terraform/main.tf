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

resource "aws_s3_bucket_public_access_block" "bad_block" {
  bucket = aws_s3_bucket.bad_bucket.id

  block_public_acls   = false
  block_public_policy = false
  ignore_public_acls  = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_acl" "bad_acl" {
  bucket = aws_s3_bucket.bad_bucket.id
  acl    = "public-read"
}

resource "aws_s3_bucket_versioning" "bad_versioning" {
  bucket = aws_s3_bucket.bad_bucket.id

  versioning_configuration {
    status = "Suspended"
  }
}