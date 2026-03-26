provider "aws" {
  region = "us-east-1"
}
 
resource "aws_instance" "app" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "m5.2xlarge"
  monitoring    = false
  tags = {
    Name = "app-server"
  }
}



