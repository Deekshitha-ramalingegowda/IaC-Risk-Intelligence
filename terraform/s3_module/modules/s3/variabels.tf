variable "bucket_name" {
  description = "Name of the S3 bucket"
  type        = string
}

variable "tags" {
  description = "Tags for S3 bucket"
  type        = map(string)
  default     = {}
}

variable "enable_versioning" {
  description = "Enable versioning"
  type        = bool
  default     = true
}

variable "sse_algorithm" {
  description = "Encryption algorithm"
  type        = string
  default     = "AES256"
}

variable "block_public_access" {
  description = "Block all public access"
  type        = bool
  default     = true
}

variable "acl" {
  description = "Canned ACL (e.g., private, public-read)"
  type        = string
  default     = null
}

variable "attach_policy" {
  description = "Whether to attach bucket policy"
  type        = bool
  default     = false
}

variable "policy_json" {
  description = "Bucket policy JSON"
  type        = string
  default     = ""
}

variable "lifecycle_rules" {
  description = "Lifecycle rules"
  type = list(object({
    id              = string
    expiration_days = number
  }))
  default = []
}