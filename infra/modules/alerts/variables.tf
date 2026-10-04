variable "resource_group_name" { type = string }
variable "resource_group_id" { type = string }
variable "location" { type = string }
variable "name_suffix" { type = string }
variable "app_insights_id" { type = string }
variable "enable_app_alerts" {
  type        = bool
  description = "Create the alerts that target the Container App (false until the app exists)."
}

variable "container_app_id" {
  type    = string
  default = null
}

variable "app_fqdn" {
  type    = string
  default = null
}
variable "action_group_id" { type = string }
variable "alert_email" { type = string }

variable "evaluation_frequency" {
  type        = string
  default     = "PT15M"
  description = "Log alert frequency. PT15M is the cheapest tier; use PT5M while demoing."
}

variable "evaluation_window" {
  type    = string
  default = "PT15M"
}

variable "min_requests" {
  type        = number
  default     = 20
  description = "Ignore windows with fewer requests (one slow cold start is not an incident)."
}

variable "latency_threshold_ms" {
  type    = number
  default = 300
}

variable "error_rate_threshold_pct" {
  type    = number
  default = 2
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
  type        = number
  default     = 100
  description = "Amount in the subscription's billing currency (not necessarily USD) over the budget's annual period."
}

variable "budget_thresholds_pct" {
  type    = list(number)
  default = [25, 50, 75]
}

variable "budget_start_date" {
  type        = string
  description = "First day of a month, RFC3339, e.g. 2026-10-01T00:00:00Z."
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "enable_drift_alert" {
  type        = bool
  default     = true
  description = "Alert on drift_check events from the drift workflow (needs only App Insights)."
}
