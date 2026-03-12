resource "aws_instance" "app" {
  ami               = "ami-0c55b159cbfafe1f0"
  instance_type     = "t3.large" 
  monitoring        = false        
  ebs_optimized     = false        

  root_block_device {
    volume_type = "gp2"   
    volume_size = 500     
    encrypted   = false    
  }

  tags = { Name = "app-server" }
}