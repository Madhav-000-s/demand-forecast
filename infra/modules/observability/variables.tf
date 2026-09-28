variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "log_analytics_name" { type = string }
variable "app_insights_name" { type = string }
variable "action_group_name" { type = string }

variable "alert_email" {
  type        = string
  description = "Address that receives every alert."
}

variable "retention_days" {
  type    = number
  default = 30
}

variable "daily_quota_gb" {
  type        = number
  default     = 0.5
  description = "Log Analytics daily ingestion cap in GB."
}

variable "tags" {
  type    = map(string)
  default = {}
}
