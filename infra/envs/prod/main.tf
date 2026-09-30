data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

# Suffix for globally unique names (registry, key vaults, storage).
resource "random_string" "suffix" {
  length  = 4
  lower   = true
  upper   = false
  numeric = true
  special = false
}

locals {
  base   = "${var.project}-${var.env}-${var.location_short}" # dfcast-prod-cin
  flat   = "${var.project}${var.env}${var.location_short}"   # dfcastprodcin
  suffix = random_string.suffix.result
  # CI passes TF_VAR_app_image="" until the first image exists; treat "" like null.
  app_enabled = try(length(var.app_image) > 0, false)
  tags = {
    project    = var.project
    env        = var.env
    owner      = var.owner
    managed_by = "terraform"
  }
}

module "observability" {
  source = "../../modules/observability"

  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  log_analytics_name  = "log-${local.base}"
  app_insights_name   = "appi-${local.base}"
  action_group_name   = "ag-${local.base}"
  alert_email         = var.alert_email
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

module "registry" {
  source = "../../modules/registry"

  name                = "cr${local.flat}${local.suffix}"
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  tags                = local.tags
}

module "keyvault" {
  source = "../../modules/keyvault"

  name                  = "kv-${local.base}-${local.suffix}"
  resource_group_name   = data.azurerm_resource_group.this.name
  location              = var.location
  tenant_id             = data.azurerm_client_config.current.tenant_id
  deployer_principal_id = data.azurerm_client_config.current.object_id
  secrets = {
    "appinsights-connection-string" = module.observability.app_insights_connection_string
  }
  tags = local.tags
}

module "container_app" {
  source = "../../modules/container_app"
  count  = local.app_enabled ? 1 : 0

  resource_group_name       = data.azurerm_resource_group.this.name
  location                  = var.location
  resource_group_id         = data.azurerm_resource_group.this.id
  environment_name          = "cae-wp-${local.base}" # new name: the old express environment is destroyed separately
  app_name                  = "ca-${local.base}"
  identity_name             = "id-${local.base}-app"
  log_analytics_customer_id = module.observability.log_analytics_customer_id
  log_analytics_shared_key  = module.observability.log_analytics_shared_key
  acr_id                    = module.registry.id
  acr_login_server          = module.registry.login_server
  key_vault_id              = module.keyvault.id
  appinsights_secret_id     = module.keyvault.secret_ids["appinsights-connection-string"]
  image                     = var.app_image
  min_replicas              = var.min_replicas
  tags                      = local.tags
}

module "alerts" {
  source = "../../modules/alerts"

  resource_group_name      = data.azurerm_resource_group.this.name
  resource_group_id        = data.azurerm_resource_group.this.id
  location                 = var.location
  name_suffix              = local.base
  app_insights_id          = module.observability.app_insights_id
  enable_app_alerts        = local.app_enabled
  container_app_id         = try(module.container_app[0].app_id, null)
  app_fqdn                 = try(module.container_app[0].fqdn, null)
  action_group_id          = module.observability.action_group_id
  alert_email              = var.alert_email
  evaluation_frequency     = var.alert_evaluation_frequency
  enable_availability_test = var.enable_availability_test
  enable_budget            = var.enable_budget
  budget_amount            = var.budget_amount
  budget_start_date        = var.budget_start_date
  tags                     = local.tags
}

module "azureml" {
  source = "../../modules/azureml"

  resource_group_name   = data.azurerm_resource_group.this.name
  location              = var.location
  tenant_id             = data.azurerm_client_config.current.tenant_id
  workspace_name        = "mlw-${local.base}"
  storage_account_name  = "st${local.flat}ml${local.suffix}"
  key_vault_name        = "kv-${var.project}-ml-${local.suffix}"
  app_insights_id       = module.observability.app_insights_id
  container_registry_id = module.registry.id
  vm_size               = var.aml_vm_size
  vm_priority           = var.aml_vm_priority
  tags                  = local.tags
}
