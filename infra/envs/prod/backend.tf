# Remote state in the storage account created by infra/bootstrap/bootstrap.sh.
# Values are supplied at init time (see backend.hcl.example / the workflows):
#   terraform init -backend-config=backend.hcl
terraform {
  backend "azurerm" {
    container_name   = "tfstate"
    key              = "prod.tfstate"
    use_azuread_auth = true
  }
}
