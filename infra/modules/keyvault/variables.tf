variable "name" {
  type        = string
  description = "Globally unique, 3-24 characters."
}
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tenant_id" { type = string }

variable "deployer_principal_id" {
  type        = string
  description = "Object id of the identity running Terraform; it gets Key Vault Secrets Officer."
}

variable "secrets" {
  type        = map(string)
  default     = {}
  sensitive   = true
  description = "Secret name => value."
}

variable "tags" {
  type    = map(string)
  default = {}
}
