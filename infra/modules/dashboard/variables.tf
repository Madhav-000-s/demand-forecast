variable "resource_group_name" { type = string }
variable "location" { type = string }

variable "app_insights_id" {
  type        = string
  description = "Workbook queries run against this Application Insights resource."
}

variable "display_name" {
  type    = string
  default = "dfcast: SLOs, canaries and drift"
}

variable "tags" {
  type    = map(string)
  default = {}
}
