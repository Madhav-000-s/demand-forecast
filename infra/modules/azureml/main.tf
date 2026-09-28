# Workspace storage: code snapshots, job outputs, the registered dataset.
resource "azurerm_storage_account" "ml" {
  name                            = var.storage_account_name
  location                        = var.location
  resource_group_name             = var.resource_group_name
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true # Azure ML datastore default; see .checkov.yaml
  tags                            = var.tags

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }

  sas_policy {
    expiration_period = "1.00:00:00"
    expiration_action = "Log"
  }
}

# Azure ML manages this vault itself through access policies, so it is kept
# separate from the app's RBAC-mode vault.
resource "azurerm_key_vault" "ml" {
  name                       = var.key_vault_name
  location                   = var.location
  resource_group_name        = var.resource_group_name
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = false
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  tags                       = var.tags

  lifecycle {
    ignore_changes = [access_policy] # populated by Azure ML
  }
}

resource "azurerm_machine_learning_workspace" "this" {
  name                          = var.workspace_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  sku_name                      = "Basic"
  application_insights_id       = var.app_insights_id
  key_vault_id                  = azurerm_key_vault.ml.id
  storage_account_id            = azurerm_storage_account.ml.id
  container_registry_id         = var.container_registry_id
  public_network_access_enabled = true
  # Build job environments on our own cluster instead of ACR Tasks, which are
  # often disabled on student and trial subscriptions.
  image_build_compute_name = var.cluster_name
  tags                     = var.tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_machine_learning_compute_cluster" "cpu" {
  name                          = var.cluster_name
  location                      = var.location
  machine_learning_workspace_id = azurerm_machine_learning_workspace.this.id
  vm_size                       = var.vm_size
  vm_priority                   = var.vm_priority
  local_auth_enabled            = false # no SSH / local accounts on nodes
  tags                          = var.tags

  scale_settings {
    min_node_count                       = 0 # no idle cost
    max_node_count                       = 1
    scale_down_nodes_after_idle_duration = "PT5M"
  }

  identity {
    type = "SystemAssigned"
  }
}
