variable "project" {
  type    = string
  default = "dfcast"
}

variable "env" {
  type    = string
  default = "prod"
}

variable "location" {
  type        = string
  default     = "centralindia"
  description = "Subscription policy allows koreacentral, indiasouthcentral, centralindia, uaenorth, malaysiawest."
}

variable "location_short" {
  type    = string
  default = "cin"
}

variable "resource_group_name" {
  type        = string
  default     = "rg-dfcast-prod-cin"
  description = "Created by infra/bootstrap/bootstrap.sh (CI's identity is scoped to it)."
}

variable "owner" {
  type    = string
  default = "madhav"
}

variable "alert_email" {
  type        = string
  description = "Receives alerts and budget notifications. Set via TF_VAR_alert_email."
}

variable "app_image" {
  type        = string
  default     = null
  description = <<-EOT
    Image for the Container App's first revision, e.g. <acr>.azurecr.io/dfcast-api:<tag>.
    Leave null on the very first apply (the registry does not exist yet); push an
    image, then set it. After the app exists deploy.yml manages images and this
    value is ignored.
  EOT
}

variable "min_replicas" {
  type        = number
  default     = 0
  description = "0 = scale to zero; set 1 while demoing so the latency SLO skips cold starts."
}

variable "log_daily_quota_gb" {
  type    = number
  default = 0.5
}

variable "alert_evaluation_frequency" {
  type    = string
  default = "PT15M"
}

variable "enable_availability_test" {
  type    = bool
  default = false
}

variable "enable_budget" {
  type    = bool
  default = true
}

variable "budget_amount" {
  type    = number
  default = 100
}

variable "budget_start_date" {
  type    = string
  default = "2026-10-01T00:00:00Z"
}

variable "aml_vm_size" {
  type    = string
  default = "Standard_DS2_v2"
}

variable "aml_vm_priority" {
  type    = string
  default = "Dedicated"
}
