variable "name" {
  type        = string
  description = "Globally unique, alphanumeric only."
}
variable "resource_group_name" { type = string }
variable "location" { type = string }
variable "tags" {
  type    = map(string)
  default = {}
}
