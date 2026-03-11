provider "aws" {
  region = "us-east-1"
}

# ============================================
# SECURITY ISSUES - INTENTIONAL MISCONFIGS
# ============================================

resource "aws_security_group" "bad_sg" {
  name = "bad-sg"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # CRITICAL: Unrestricted SSH
  }
}

# Security Group with open database port
resource "aws_security_group" "db_exposed" {
  name        = "db-exposed-sg"
  description = "Database security group with exposed ports"

  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # CRITICAL: MySQL exposed to internet
  }

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # CRITICAL: PostgreSQL exposed to internet
  }
}

# S3 Bucket with public access and no encryption
resource "aws_s3_bucket" "insecure_bucket" {
  bucket = "insecure-data-bucket-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "insecure_bucket_pab" {
  bucket = aws_s3_bucket.insecure_bucket.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# S3 Bucket ACL set to public-read (CRITICAL: sensitive data exposed)
resource "aws_s3_bucket_acl" "insecure_bucket_acl" {
  bucket = aws_s3_bucket.insecure_bucket.id
  acl    = "public-read"
}

# Unencrypted EBS Volume (large - cost and security issue)
resource "aws_ebs_volume" "unencrypted_large_volume" {
  availability_zone = "us-east-1a"
  size              = 500  # Large volume - high cost

  # NOTE: No encryption by default - security issue
  tags = {
    Name = "unencrypted-volume"
  }
}

# Unencrypted EBS Snapshot
resource "aws_ebs_snapshot" "unencrypted_snapshot" {
  volume_id   = aws_ebs_volume.unencrypted_large_volume.id
  description = "Unencrypted snapshot - security issue"

  tags = {
    Name = "unencrypted-snapshot"
  }
}

# IAM Role with overpermissive policy
resource "aws_iam_role" "overpermissive_role" {
  name = "overpermissive-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

# Overpermissive IAM Policy (CRITICAL: too broad permissions)
resource "aws_iam_role_policy" "overpermissive_policy" {
  name = "overpermissive-policy"
  role = aws_iam_role.overpermissive_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "*"  # CRITICAL: Allow all actions on all resources
        Resource = "*"
      }
    ]
  })
}

# ============================================
# COST OPTIMIZATION ISSUES - OVERSIZED RESOURCES
# ============================================

# Large, expensive EC2 instance (m5.2xlarge - ~$0.384/hour)
resource "aws_instance" "oversized_instance" {
  ami                    = "ami-0c55b159cbfafe1f0"  # Amazon Linux 2
  instance_type          = "m5.2xlarge"            # EXPENSIVE: Could be downsized
  availability_zone      = "us-east-1a"
  monitoring             = false                   # Missing monitoring - cost issue
  ebs_optimized          = false                   # Not optimized - performance/cost issue

  root_block_device {
    volume_type           = "gp2"
    volume_size           = 500  # Large root volume - unnecessary
    delete_on_termination = true
    encrypted             = false
  }

  tags = {
    Name = "oversized-instance"
  }
}

# Expensive RDS instance (db.r5.2xlarge - single-AZ, no Multi-AZ)
resource "aws_db_instance" "expensive_rds" {
  identifier     = "expensive-mysql-db"
  engine         = "mysql"
  engine_version = "8.0.35"
  instance_class = "db.r5.2xlarge"  # EXPENSIVE: High-memory instance
  allocated_storage = 1000            # Large storage allocation
  storage_type   = "gp2"

  db_name                    = "mydb"
  username                   = "admin"
  password                   = "TempPassword123!"  # CRITICAL: Hardcoded password in code - is this an issue?

  multi_az               = false         # RISK: No high availability
  publicly_accessible    = true          # CRITICAL: Exposed to internet
  storage_encrypted      = false         # CRITICAL: No encryption
  backup_retention_period = 0            # CRITICAL: No backups
  skip_final_snapshot     = true

  tags = {
    Name = "expensive-rds"
  }
}

# NAT Gateway (high data transfer costs)
resource "aws_eip" "nat_eip" {
  domain = "vpc"

  tags = {
    Name = "nat-eip"
  }
}

resource "aws_internet_gateway" "main" {
  tags = {
    Name = "main-igw"
  }
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "public" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1a"

  tags = {
    Name = "public-subnet"
  }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat_eip.id
  subnet_id     = aws_subnet.public.id

  tags = {
    Name = "main-nat"
  }

  depends_on = [aws_internet_gateway.main]
}

# Multiple unattached EBS volumes (wasted cost)
resource "aws_ebs_volume" "unused_volume_1" {
  availability_zone = "us-east-1a"
  size              = 100

  tags = {
    Name = "unused-volume-1"
  }
}

resource "aws_ebs_volume" "unused_volume_2" {
  availability_zone = "us-east-1a"
  size              = 200

  tags = {
    Name = "unused-volume-2"
  }
}

# ============================================
# WELL-CONFIGURED RESOURCES (for comparison)
# ============================================

# Properly encrypted and configured S3 bucket
resource "aws_s3_bucket" "secure_bucket" {
  bucket = "secure-data-bucket-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name = "secure-bucket"
  }
}

resource "aws_s3_bucket_versioning" "secure_bucket_versioning" {
  bucket = aws_s3_bucket.secure_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "secure_bucket_encryption" {
  bucket = aws_s3_bucket.secure_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "secure_bucket_pab" {
  bucket = aws_s3_bucket.secure_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Restrictive security group
resource "aws_security_group" "restricted_sg" {
  name        = "restricted-sg"
  description = "Restrictive security group - best practice"

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.restricted_sg.id]  # Only from itself
    description     = "HTTPS from internal only"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name = "restricted-sg"
  }
}

# Cost-optimized small EC2 instance
resource "aws_instance" "optimized_instance" {
  ami               = "ami-0c55b159cbfafe1f0"  # Amazon Linux 2
  instance_type     = "t3.micro"               # Cost-effective, eligible for free tier
  availability_zone = "us-east-1a"
  monitoring        = true

  root_block_device {
    volume_type           = "gp3"  # Better than gp2
    volume_size           = 20    # Only what's needed
    delete_on_termination = true
    encrypted             = true  # Encrypted for security
  }

  tags = {
    Name = "optimized-instance"
  }
}

# Data source for current AWS account
data "aws_caller_identity" "current" {}








