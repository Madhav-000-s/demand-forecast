output "workbook_id" { value = azurerm_application_insights_workbook.this.id }

output "workbook_json" {
  description = "Serialized workbook (for tests and review)."
  value       = local.workbook_json
}
