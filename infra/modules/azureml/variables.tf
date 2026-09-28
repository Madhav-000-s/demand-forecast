variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tenant_id" { type = string }
variable "workspace_name" { type = string }
variable "storage_account_name" { type = string }
variable "key_vault_name" { type = string }
variable "app_insights_id" { type = string }
variable "container_registry_id" { type = string }

variable "cluster_name" {
  type    = string
  default = "cpu-cluster"
}

variable "vm_size" {
  type        = string
  default     = "Standard_DS2_v2"
  description = "2 vCPU / 7 GB; training takes ~2 minutes. Check vCPU quota for the family first."
}

variable "vm_priority" {
  type        = string
  default     = "Dedicated"
  description = "Dedicated or LowPriority (cheaper, but student subscriptions often have 0 low-priority quota)."
}

variable "tags" {
  type    = map(string)
  default = {}
}
