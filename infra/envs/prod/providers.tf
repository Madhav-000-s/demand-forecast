# Credentials come from the environment: Azure CLI locally, OIDC in GitHub Actions
# (ARM_USE_OIDC, ARM_CLIENT_ID, ARM_TENANT_ID, ARM_SUBSCRIPTION_ID).
provider "azurerm" {
  # Resource providers are registered once by the bootstrap script; CI's identity
  # is scoped to the resource group and cannot register them.
  resource_provider_registrations = "none"
  storage_use_azuread             = true

  features {
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
    machine_learning {
      purge_soft_deleted_workspace_on_destroy = true
    }
    application_insights {
      disable_generated_rule = true
    }
  }
}
