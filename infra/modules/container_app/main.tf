resource "azurerm_user_assigned_identity" "app" {
  name                = var.identity_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "kv_secrets_user" {
  scope                = var.key_vault_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
  principal_type       = "ServicePrincipal"
}

# The app cannot pull its image or read its secrets until these roles propagate.
resource "time_sleep" "rbac_propagation" {
  depends_on      = [azurerm_role_assignment.acr_pull, azurerm_role_assignment.kv_secrets_user]
  create_duration = "60s"
}

# The environment is created through AzAPI because azurerm (API 2025-07-01)
# cannot set `environmentMode`, and Azure then picks the "express" mode, which
# has no multiple revisions, traffic splitting, labels, managed-identity image
# pulls, Key Vault references or probes. API 2026-07-01 lets us ask for a
# standard workload-profiles environment explicitly. The Consumption profile is
# serverless (scale to zero, no base fee).
resource "azapi_resource" "environment" {
  type      = "Microsoft.App/managedEnvironments@2026-07-01"
  name      = var.environment_name
  parent_id = var.resource_group_id
  location  = var.location
  tags      = var.tags

  # AzAPI's embedded schemas stop at 2026-01-01; Azure validates the request.
  schema_validation_enabled = false

  body = {
    properties = {
      environmentMode = "WorkloadProfiles"
      zoneRedundant   = false
      workloadProfiles = [
        {
          name                = "Consumption"
          workloadProfileType = "Consumption"
        }
      ]
      appLogsConfiguration = {
        destination = "log-analytics"
        logAnalyticsConfiguration = {
          customerId = var.log_analytics_customer_id
        }
      }
    }
  }

  # Write-only: never read back, never shown in plans.
  sensitive_body = {
    properties = {
      appLogsConfiguration = {
        logAnalyticsConfiguration = {
          sharedKey = var.log_analytics_shared_key
        }
      }
    }
  }

  response_export_values = ["properties.defaultDomain", "properties.environmentMode"]

  lifecycle {
    postcondition {
      condition     = self.output.properties.environmentMode == "WorkloadProfiles"
      error_message = "Container Apps environment is not in WorkloadProfiles mode; canary releases need a standard environment."
    }
  }
}

resource "azurerm_container_app" "this" {
  name                         = var.app_name
  container_app_environment_id = azapi_resource.environment.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Multiple" # canary deploys split traffic between revisions
  workload_profile_name        = "Consumption"
  max_inactive_revisions       = 10
  tags                         = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = var.acr_login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  secret {
    name                = "appinsights-connection-string"
    key_vault_secret_id = var.appinsights_secret_id
    identity            = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas                     = var.min_replicas
    max_replicas                     = var.max_replicas
    termination_grace_period_seconds = 30

    container {
      name   = "api"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "appinsights-connection-string"
      }
      env {
        name  = "OTEL_SERVICE_NAME"
        value = "dfcast-api"
      }
      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      # Model load + warm-up gets up to 2 minutes (24 x 5 s).
      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/readyz"
        interval_seconds        = 5
        failure_count_threshold = 24
      }
      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/readyz"
        interval_seconds        = 10
        failure_count_threshold = 3
      }
      liveness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/healthz"
        interval_seconds        = 15
        failure_count_threshold = 3
      }
    }

    http_scale_rule {
      name                = "http-concurrency"
      concurrent_requests = tostring(var.scale_concurrent_requests)
    }
  }

  # deploy.yml owns the image, revision names and traffic split (canary releases).
  # Terraform owns everything else.
  lifecycle {
    ignore_changes = [
      template[0].container[0].image,
      template[0].revision_suffix,
      ingress[0].traffic_weight,
    ]
  }

  depends_on = [time_sleep.rbac_propagation]
}
