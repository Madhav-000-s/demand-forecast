output "workspace_id" { value = azurerm_machine_learning_workspace.this.id }
output "workspace_name" { value = azurerm_machine_learning_workspace.this.name }
output "cluster_name" { value = azurerm_machine_learning_compute_cluster.cpu.name }
output "storage_account_name" { value = azurerm_storage_account.ml.name }
