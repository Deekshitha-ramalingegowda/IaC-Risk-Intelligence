output "ec2_instance_id"   { value = module.infra.ec2_instance_id }
output "ec2_private_ip"    { value = module.infra.ec2_private_ip }
output "s3_bucket_id"      { value = module.infra.s3_bucket_id }
output "s3_bucket_arn"     { value = module.infra.s3_bucket_arn }
output "vpc_id"            { value = module.infra.vpc_id }
output "private_subnet_ids"{ value = module.infra.private_subnet_ids }
output "rds_endpoint"      { value = module.infra.rds_endpoint }
output "rds_instance_id"   { value = module.infra.rds_instance_id }