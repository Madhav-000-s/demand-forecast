output "alert_ids" {
  value = concat(
    azurerm_monitor_scheduled_query_rules_alert_v2.latency[*].id,
    azurerm_monitor_scheduled_query_rules_alert_v2.errors[*].id,
    azurerm_monitor_metric_alert.restarts[*].id,
    azurerm_monitor_metric_alert.availability[*].id,
  )
}
