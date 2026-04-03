resource "aws_s3_bucket" "bucket" {
  bucket = var.bucket_name
  tags = var.tags
}

# Versioning
resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.bucket.id

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

# Encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "encryption" {
  bucket = aws_s3_bucket.bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = var.sse_algorithm
    }
  }
}

# Public access block (toggle)
resource "aws_s3_bucket_public_access_block" "public_access" {
  bucket = aws_s3_bucket.bucket.id

  block_public_acls       = var.block_public_access
  block_public_policy     = var.block_public_access
  ignore_public_acls      = var.block_public_access
  restrict_public_buckets = var.block_public_access
}

# Bucket ACL (optional)
resource "aws_s3_bucket_acl" "acl" {
  count  = var.acl != null ? 1 : 0
  bucket = aws_s3_bucket.bucket.id
  acl    = var.acl
}

# Bucket Policy (optional)
resource "aws_s3_bucket_policy" "policy" {
  count  = var.attach_policy ? 1 : 0
  bucket = aws_s3_bucket.bucket.id
  policy = var.policy_json
}

# Lifecycle configuration
resource "aws_s3_bucket_lifecycle_configuration" "lifecycle" {
  count  = length(var.lifecycle_rules) > 0 ? 1 : 0
  bucket = aws_s3_bucket.bucket.id

  dynamic "rule" {
    for_each = var.lifecycle_rules
    content {
      id     = rule.value.id
      status = "Enabled"

      expiration {
        days = rule.value.expiration_days
      }
    }
  }
}