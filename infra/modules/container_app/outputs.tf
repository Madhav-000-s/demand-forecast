output "app_id" { value = azurerm_container_app.this.id }
output "app_name" { value = azurerm_container_app.this.name }
output "fqdn" { value = azurerm_container_app.this.ingress[0].fqdn }
output "environment_default_domain" { value = azapi_resource.environment.output.properties.defaultDomain }
output "identity_principal_id" { value = azurerm_user_assigned_identity.app.principal_id }
output "environment_mode_requested" { value = azapi_resource.environment.body.properties.environmentMode }

output "scaling" {
  description = "Replica size and scale rule (inputs, known at plan time; for tests and review)."
  value = {
    cpu                       = var.cpu
    memory                    = var.memory
    min_replicas              = var.min_replicas
    max_replicas              = var.max_replicas
    scale_concurrent_requests = var.scale_concurrent_requests
  }
}
