output "app_id" { value = azurerm_container_app.this.id }
output "app_name" { value = azurerm_container_app.this.name }
output "fqdn" { value = azurerm_container_app.this.ingress[0].fqdn }
output "environment_default_domain" { value = azurerm_container_app_environment.this.default_domain }
output "identity_principal_id" { value = azurerm_user_assigned_identity.app.principal_id }
