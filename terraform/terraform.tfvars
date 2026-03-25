region = "ap-south-1"
project_name = "infra-demo"

vpc_cidr = "10.0.0.0/16"
public_subnet_cidr = "10.0.1.0/24"
az = "ap-south-1a"

ami_id = "ami-0f58b397bc5c1f2e8" # Amazon Linux (example)
instance_type = "t3.micro"

key_name = "your-key"

tags = {
  Environment = "dev"
  Owner       = "Deekshitha"
}