output "id" { value = azurerm_key_vault.this.id }
output "name" { value = azurerm_key_vault.this.name }
output "uri" { value = azurerm_key_vault.this.vault_uri }

output "secret_ids" {
  description = "Secret name => versionless id (always resolves to the latest version)."
  value       = { for k, s in azurerm_key_vault_secret.this : k => s.versionless_id }
}
