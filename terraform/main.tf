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







