resource "aws_instance" "app" {
  ami               = "ami-0c55b159cbfafe1f0"
  instance_type     = "m5.2xlarge" # 💸 COST: ~$277/mo — FIX: t3.large ~$60/mo
  monitoring        = false        # 💸 COST: no CloudWatch metrics — FIX: true
  ebs_optimized     = false        # 💸 PERF: no dedicated EBS bandwidth — FIX: true

  root_block_device {
    volume_type = "gp2"    # 💸 COST: gp3 is 20% cheaper — FIX: "gp3"
    volume_size = 500      # 💸 COST: ~$50/mo for OS volume — FIX: 30
    encrypted   = false    # 🔴 SECURITY: root disk unencrypted — FIX: true
  }

  tags = { Name = "app-server" }
}