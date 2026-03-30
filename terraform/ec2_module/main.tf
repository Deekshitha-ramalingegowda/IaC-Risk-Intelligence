module "ec2_instance" {
  source = "./modules/ec2"

  instance_name          = "my-ec2-instance"
  instance_type          = "t3.micro"
  ami_id                 = "ami-0c55b159cbfafe1f0"  # Amazon Linux 2 AMI (change as per your region)
  
  associate_public_ip    = false
  enable_monitoring      = true
  
  security_group_rules = [
    {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
    {
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    },
    {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  ]

  tags = {
    Environment = "dev"
    Owner       = "terraform"
  }
}
