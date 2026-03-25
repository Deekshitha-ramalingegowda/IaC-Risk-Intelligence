aws_region   = "us-east-1"
project_name = "demo"

vpc_cidr            = "10.0.0.0/16"
public_subnet_cidr  = "10.0.1.0/24"
private_subnet_cidr = "10.0.2.0/24"
availability_zone   = "us-east-1a"

# Change to "m5.large" to save ~$207/mo
ec2_instance_type = "m5.2xlarge"
ami_id            = "ami-0c02fb55956c7d316"

tags = {
  Environment = "dev"
  ManagedBy   = "terraform"
  Owner       = "platform-team"
}