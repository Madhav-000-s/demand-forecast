variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "environment_name" { type = string }
variable "app_name" { type = string }
variable "identity_name" { type = string }
variable "log_analytics_workspace_id" { type = string }
variable "acr_id" { type = string }
variable "acr_login_server" { type = string }
variable "key_vault_id" { type = string }

variable "appinsights_secret_id" {
  type        = string
  description = "Versionless Key Vault secret id holding the App Insights connection string."
}

variable "image" {
  type        = string
  description = "Image for the first revision only; deploy.yml manages images afterwards."
}

variable "min_replicas" {
  type        = number
  default     = 0
  description = "0 = scale to zero when idle (cold starts); 1 = always warm."
}

variable "max_replicas" {
  type    = number
  default = 3
}

variable "cpu" {
  type    = number
  default = 0.5
}

variable "memory" {
  type    = string
  default = "1Gi"
}

variable "scale_concurrent_requests" {
  type    = number
  default = 50
}

variable "tags" {
  type    = map(string)
  default = {}
}
