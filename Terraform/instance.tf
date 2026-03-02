 resource "aws_instance" "web_server"{
    ami = ""
    key_name = "my_key_pair"
    instance_type = "t2.micro"
    tags = {
        Name = "WebServer-"
    }
 }