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

resource "azurerm_container_app_environment" "this" {
  name                       = var.environment_name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  log_analytics_workspace_id = var.log_analytics_workspace_id
  logs_destination           = "log-analytics"
  tags                       = var.tags

  # A workload-profiles environment is always a *standard* environment. Without
  # a profile, Azure may create an "express" environment, which does not support
  # multiple revisions, traffic splitting, labels, managed-identity image pulls,
  # Key Vault references or probes - all needed for canary releases.
  # The Consumption profile is serverless (scale to zero, no base fee).
  # Profiles cannot be added later; changing this recreates the environment.
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }
}

resource "azurerm_container_app" "this" {
  name                         = var.app_name
  container_app_environment_id = azurerm_container_app_environment.this.id
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
