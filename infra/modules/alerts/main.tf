locals {
  # Requests to the forecast endpoints only (probes are not traced).
  api_requests = "requests | where name has '/v1/'"
}

# --- SLO alerts (log queries over App Insights) -------------------------------

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "latency" {
  count = var.enable_app_alerts ? 1 : 0

  name                 = "alert-latency-p95-${var.name_suffix}"
  display_name         = "Forecast p95 latency above ${var.latency_threshold_ms} ms"
  description          = "Latency SLO: 99% of /v1 requests under 300 ms. Runbook: docs/runbooks/latency.md"
  resource_group_name  = var.resource_group_name
  location             = var.location
  scopes               = [var.app_insights_id]
  severity             = 2
  evaluation_frequency = var.evaluation_frequency
  window_duration      = var.evaluation_window
  tags                 = var.tags

  criteria {
    query                   = <<-KQL
      ${local.api_requests}
      | summarize p95 = percentile(duration, 95), n = count()
      | where n >= ${var.min_requests}
      | project p95
    KQL
    metric_measure_column   = "p95"
    time_aggregation_method = "Maximum"
    operator                = "GreaterThan"
    threshold               = var.latency_threshold_ms

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [var.action_group_id]
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "errors" {
  count = var.enable_app_alerts ? 1 : 0

  name                 = "alert-5xx-rate-${var.name_suffix}"
  display_name         = "Forecast 5xx rate above ${var.error_rate_threshold_pct}%"
  description          = "Availability SLO: 99.5% of /v1 requests non-5xx. Runbook: docs/runbooks/errors.md"
  resource_group_name  = var.resource_group_name
  location             = var.location
  scopes               = [var.app_insights_id]
  severity             = 1
  evaluation_frequency = var.evaluation_frequency
  window_duration      = var.evaluation_window
  tags                 = var.tags

  criteria {
    query                   = <<-KQL
      ${local.api_requests}
      | summarize n = count(), errors = countif(toint(resultCode) >= 500)
      | where n >= ${var.min_requests}
      | project error_rate_pct = 100.0 * errors / n
    KQL
    metric_measure_column   = "error_rate_pct"
    time_aggregation_method = "Maximum"
    operator                = "GreaterThan"
    threshold               = var.error_rate_threshold_pct

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [var.action_group_id]
  }
}

# --- Platform alerts (metrics) ------------------------------------------------

resource "azurerm_monitor_metric_alert" "restarts" {
  count = var.enable_app_alerts ? 1 : 0

  name                = "alert-restarts-${var.name_suffix}"
  description         = "More than 3 replica restarts in 15 minutes. Runbook: docs/runbooks/restarts.md"
  resource_group_name = var.resource_group_name
  scopes              = [var.container_app_id]
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"
  tags                = var.tags

  criteria {
    metric_namespace       = "Microsoft.App/containerApps"
    metric_name            = "RestartCount"
    aggregation            = "Total"
    operator               = "GreaterThan"
    threshold              = 3
    skip_metric_validation = true # metric only exists once replicas have run
  }

  action {
    action_group_id = var.action_group_id
  }
}

# Availability test from several regions. Off by default: every probe run costs
# money and keeps a replica awake, which defeats scale-to-zero.
resource "azurerm_application_insights_standard_web_test" "healthz" {
  count = var.enable_app_alerts && var.enable_availability_test ? 1 : 0

  name                    = "webtest-healthz-${var.name_suffix}"
  resource_group_name     = var.resource_group_name
  location                = var.location
  application_insights_id = var.app_insights_id
  geo_locations           = ["apac-sg-sin-azr", "apac-hk-hkn-azr", "emea-nl-ams-azr"]
  frequency               = 900
  timeout                 = 30
  retry_enabled           = true
  enabled                 = true
  tags                    = var.tags

  request {
    url = "https://${var.app_fqdn}/healthz"
  }

  validation_rules {
    expected_status_code = 200
    ssl_check_enabled    = true
  }
}

resource "azurerm_monitor_metric_alert" "availability" {
  count = var.enable_app_alerts && var.enable_availability_test ? 1 : 0

  name                = "alert-availability-${var.name_suffix}"
  description         = "/healthz failing from 2 or more locations. Runbook: docs/runbooks/availability.md"
  resource_group_name = var.resource_group_name
  scopes              = [azurerm_application_insights_standard_web_test.healthz[0].id, var.app_insights_id]
  severity            = 1
  tags                = var.tags

  application_insights_web_test_location_availability_criteria {
    web_test_id           = azurerm_application_insights_standard_web_test.healthz[0].id
    component_id          = var.app_insights_id
    failed_location_count = 2
  }

  action {
    action_group_id = var.action_group_id
  }
}

# --- Cost ---------------------------------------------------------------------

# Annual budget over the credit: emails at $25 / $50 / $75 actual spend and when
# the forecast crosses the full amount.
resource "azurerm_consumption_budget_resource_group" "credit" {
  count = var.enable_budget ? 1 : 0

  name              = "budget-${var.name_suffix}"
  resource_group_id = var.resource_group_id
  amount            = var.budget_amount
  time_grain        = "Annually"

  time_period {
    start_date = var.budget_start_date
  }

  dynamic "notification" {
    for_each = toset(var.budget_thresholds_pct)
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_emails = [var.alert_email]
    }
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Forecasted"
    contact_emails = [var.alert_email]
  }

  lifecycle {
    ignore_changes = [time_period] # Azure normalises the start date format
  }
}
