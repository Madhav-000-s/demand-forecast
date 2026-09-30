# Azure Monitor workbook over Application Insights: SLOs and error budget,
# latency and errors, canary traffic by revision, model outputs, drift job
# results, cold starts. Each panel's KQL lives in queries/*.kql so it can be
# reviewed (and pasted into Logs) on its own.

locals {
  source_id = lower(var.app_insights_id)

  # (name, title, query file, visualization, width %, fixed time range in ms or null)
  panels = [
    ["slo", "SLOs, last 28 days (targets: availability 99.5%, latency 99% < 300 ms)", "slo_summary", "table", "100", 2419200000],
    ["burn", "Error-budget burn rate (1.0 = on budget; > 14.4 over 1 h or > 6 over 6 h is fast burn)", "burn_rate", "table", "100", 259200000],
    ["latency", "Latency percentiles (ms) against the 300 ms SLO", "latency", "timechart", "50", null],
    ["errors", "Requests and 5xx rate (%)", "errors_volume", "timechart", "50", null],
    ["revisions", "Traffic by revision (canary splits)", "traffic_by_revision", "timechart", "50", null],
    ["sources", "Traffic by source", "traffic_by_source", "piechart", "50", null],
    ["units", "Mean predicted units per forecast, by model", "predicted_units", "timechart", "50", null],
    ["horizons", "Forecast horizons requested", "horizon_mix", "piechart", "50", null],
    ["drift_history", "Drift: max PSI per drift-job run (alert above 0.25)", "drift_history", "timechart", "50", 2419200000],
    ["drift_latest", "Drift: PSI per feature, latest run", "drift_latest", "table", "50", 2419200000],
    ["drift_runs", "Drift job runs", "drift_runs", "table", "100", 2419200000],
    ["cold_starts", "Replica starts (model load time)", "cold_starts", "table", "50", null],
    ["failures", "Recent 5xx responses", "failures", "table", "50", null],
  ]

  # Optional keys are added with single-entry for-expressions: a conditional
  # between objects of different shapes is a type error in HCL.
  query_items = [
    for p in local.panels : merge(
      {
        type = 3
        name = p[0]
        content = merge(
          {
            version       = "KqlItem/1.0"
            title         = p[1]
            query         = file("${path.module}/queries/${p[2]}.kql")
            size          = 0
            queryType     = 0
            resourceType  = "microsoft.insights/components"
            visualization = p[3]
          },
          { for k, v in { timeContextFromParameter = "TimeRange" } : k => v if p[5] == null },
          { for k, v in { timeContext = { durationMs = p[5] } } : k => v if p[5] != null },
        )
      },
      { for k, v in { customWidth = p[4] } : k => v if p[4] != "100" },
    )
  ]

  workbook = {
    version = "Notebook/1.0"
    items = concat(
      [
        {
          type = 1
          name = "header"
          content = {
            json = join("\n", [
              "## dfcast: demand forecast API",
              "SLOs over 28 days: **99.5%** of `/v1` requests non-5xx, **99%** under **300 ms**.",
              "Drift is checked every 6 h by the `drift` workflow (PSI per feature, alert above 0.25).",
              "Runbooks: `docs/runbooks/` in the repository.",
            ])
          }
        },
        {
          type = 9
          name = "parameters"
          content = {
            version = "KqlParameterItem/1.0"
            parameters = [
              {
                id         = "7c0a3c52-4a8e-4f9b-9d57-0c4e5a3e1d11"
                version    = "KqlParameterItem/1.0"
                name       = "TimeRange"
                label      = "Time range"
                type       = 4
                isRequired = true
                value      = { durationMs = 86400000 }
                typeSettings = {
                  selectableValues = [
                    { durationMs = 3600000 },
                    { durationMs = 21600000 },
                    { durationMs = 86400000 },
                    { durationMs = 604800000 },
                    { durationMs = 2419200000 },
                  ]
                }
              },
            ]
            style        = "pills"
            queryType    = 0
            resourceType = "microsoft.insights/components"
          }
        },
      ],
      local.query_items,
    )
    isLocked            = false
    fallbackResourceIds = [local.source_id]
  }

  workbook_json = jsonencode(local.workbook)
}

resource "azurerm_application_insights_workbook" "this" {
  name                = uuidv5("url", "https://github.com/Madhav-000-s/demand-forecast/workbooks/slo")
  resource_group_name = var.resource_group_name
  location            = var.location
  display_name        = var.display_name
  source_id           = local.source_id
  category            = "workbook"
  data_json           = local.workbook_json
  tags                = var.tags
}
