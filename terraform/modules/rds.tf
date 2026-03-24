resource "aws_db_instance" "app" {
  engine             = var.db_engine
  engine_version     = var.db_engine_version
  instance_class     = var.db_instance_class
  allocated_storage  = var.db_allocated_storage
  storage_type       = "gp3"
  storage_encrypted  = true
  db_name            = var.db_name

  manage_master_user_password         = true
  publicly_accessible                 = false
  multi_az                            = true
  backup_retention_period             = 7
  auto_minor_version_upgrade          = true
  iam_database_authentication_enabled = true
  deletion_protection                 = true
  copy_tags_to_snapshot               = true

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  monitoring_interval = 60
  monitoring_role_arn = var.rds_monitoring_role_arn

  enabled_cloudwatch_logs_exports = ["error", "slowquery", "general"]

  tags = var.tags
}

