# Plan-time tests with mocked providers: no Azure credentials needed.
#   cd infra/envs/prod && terraform init -backend=false && terraform test

mock_provider "azurerm" {
  mock_data "azurerm_client_config" {
    defaults = {
      tenant_id       = "00000000-0000-0000-0000-000000000001"
      object_id       = "00000000-0000-0000-0000-000000000002"
      subscription_id = "00000000-0000-0000-0000-000000000003"
    }
  }
  mock_data "azurerm_resource_group" {
    defaults = {
      id       = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin"
      location = "centralindia"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.OperationalInsights/workspaces/log-dfcast-prod-cin"
    }
  }
  mock_resource "azurerm_application_insights" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.Insights/components/appi-dfcast-prod-cin"
    }
  }
  mock_resource "azurerm_monitor_action_group" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.Insights/actionGroups/ag-dfcast-prod-cin"
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.ContainerRegistry/registries/crdfcastprodcinabcd"
      login_server = "crdfcastprodcinabcd.azurecr.io"
    }
  }
  mock_resource "azurerm_key_vault" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.KeyVault/vaults/kv-dfcast-prod-cin-abcd"
    }
  }
  mock_resource "azurerm_storage_account" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.Storage/storageAccounts/stdfcastprodcinmlabcd"
    }
  }
  mock_resource "azurerm_machine_learning_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.MachineLearningServices/workspaces/mlw-dfcast-prod-cin"
    }
  }
  mock_resource "azurerm_user_assigned_identity" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-dfcast-prod-cin-app"
      principal_id = "00000000-0000-0000-0000-000000000004"
      client_id    = "00000000-0000-0000-0000-000000000005"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.App/managedEnvironments/cae-dfcast-prod-cin"
    }
  }
  mock_resource "azurerm_container_app" {
    defaults = {
      id      = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.App/containerApps/ca-dfcast-prod-cin"
      ingress = { fqdn = "ca-dfcast-prod-cin.example.centralindia.azurecontainerapps.io" }
    }
  }
  mock_resource "azurerm_key_vault_secret" {
    defaults = {
      versionless_id = "https://kv-dfcast-prod-cin-abcd.vault.azure.net/secrets/appinsights-connection-string"
    }
  }
}

# Mock generators ignore length/charset settings, so pin a realistic suffix
# (4 lowercase alphanumerics, as random_string.suffix produces for real).
mock_provider "random" {
  mock_resource "random_string" {
    defaults = {
      result = "a1b2"
    }
  }
}
mock_provider "time" {}

mock_provider "azapi" {
  mock_resource "azapi_resource" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000003/resourceGroups/rg-dfcast-prod-cin/providers/Microsoft.App/managedEnvironments/cae-wp-dfcast-prod-cin"
      output = {
        properties = {
          defaultDomain   = "example.centralindia.azurecontainerapps.io"
          environmentMode = "WorkloadProfiles"
        }
      }
    }
  }
}

variables {
  alert_email = "alerts@example.com"
}

run "first_apply_without_an_image" {
  command = plan

  variables {
    app_image = ""
  }

  assert {
    condition     = length(module.container_app) == 0
    error_message = "No Container App should be planned before an image exists"
  }
  assert {
    condition     = length(module.alerts.alert_ids) == 0
    error_message = "App alerts need the app"
  }
  assert {
    condition     = output.container_app_name == null
    error_message = "container_app_name should be null before the app exists"
  }
}

run "app_and_alerts_with_an_image" {
  command = plan

  variables {
    app_image = "crdfcastprodcinabcd.azurecr.io/dfcast-api:abc1234-m1"
  }

  assert {
    condition     = length(module.container_app) == 1
    error_message = "Container App should be planned once app_image is set"
  }
  assert {
    condition     = output.container_app_name == "ca-dfcast-prod-cin"
    error_message = "Unexpected app name"
  }
  assert {
    condition     = module.container_app[0].environment_mode_requested == "WorkloadProfiles"
    error_message = "The environment must request WorkloadProfiles mode (express lacks revisions and traffic splitting)"
  }
}

run "global_names_fit_azure_limits" {
  command = apply # mocked: resolves random_string so names are known

  variables {
    app_image = ""
  }

  assert {
    condition     = can(regex("^[a-z0-9]{5,50}$", module.registry.name))
    error_message = "ACR name must be 5-50 lowercase alphanumerics: ${module.registry.name}"
  }
  assert {
    condition     = length("kv-dfcast-prod-cin-${random_string.suffix.result}") <= 24
    error_message = "Key Vault name longer than 24 characters"
  }
  assert {
    condition     = can(regex("^[a-z0-9]{3,24}$", module.azureml.storage_account_name))
    error_message = "Storage account name must be 3-24 lowercase alphanumerics"
  }
}
