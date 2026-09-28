resource "azurerm_container_registry" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "Basic"
  admin_enabled       = false # pulls use managed identity, pushes use the CI identity
  tags                = var.tags
}
