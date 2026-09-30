output "alert_ids" {
  value = concat(
    azurerm_monitor_scheduled_query_rules_alert_v2.latency[*].id,
    azurerm_monitor_scheduled_query_rules_alert_v2.errors[*].id,
    azurerm_monitor_metric_alert.restarts[*].id,
    azurerm_monitor_metric_alert.availability[*].id,
  )
}

output "drift_alert_id" {
  value = try(azurerm_monitor_scheduled_query_rules_alert_v2.drift[0].id, null)
}

output "drift_alert_enabled" {
  description = "Known at plan time (unlike the id), for tests."
  value       = length(azurerm_monitor_scheduled_query_rules_alert_v2.drift) == 1
}
