 resource "aws_instance" "web_server"{
    ami = "data.aws_ami.amazon_linux.id"
    key_name = "my_key_pair"
    instance_type = "t2.micro"
    subnet_id              = aws_subnet.public_subnet.id
    vpc_security_group_ids = [aws_security_group.ec2_sg.id]
    ebs_optimized = false



    tags = {
        Name = "WebServer"
    }
 }

 data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-hvm-*-x86_64-gp2"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
 }







