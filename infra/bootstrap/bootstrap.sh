#!/usr/bin/env bash
# One-time bootstrap, run by a subscription Owner (Azure Cloud Shell, bash):
#
#   bash infra/bootstrap/bootstrap.sh
#
# Creates what Terraform and CI need before Terraform can run:
#   1. registers the resource providers the project uses
#   2. rg-dfcast-tfstate-cin + a versioned storage account for Terraform state
#   3. rg-dfcast-prod-cin, the resource group Terraform deploys into
#   4. id-dfcast-github-cin: a user-assigned managed identity that GitHub Actions
#      logs in as through OIDC federation (no client secret anywhere), with
#        - Contributor + User Access Administrator on rg-dfcast-prod-cin only
#        - Storage Blob Data Contributor on the state account
#   5. your own Storage Blob Data Contributor on the state account (local runs)
#
# Safe to re-run: every step checks for what already exists.
set -euo pipefail

GITHUB_REPO="${GITHUB_REPO:-Madhav-000-s/demand-forecast}"
LOCATION="${LOCATION:-centralindia}"
STATE_RG="${STATE_RG:-rg-dfcast-tfstate-cin}"
PROJECT_RG="${PROJECT_RG:-rg-dfcast-prod-cin}"
IDENTITY="${IDENTITY:-id-dfcast-github-cin}"
TAGS=(project=dfcast owner=madhav managed_by=bootstrap)

log() { printf '\n==> %s\n' "$*"; }

SUBSCRIPTION_ID=$(az account show --query id -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)
log "Subscription $SUBSCRIPTION_ID ($(az account show --query name -o tsv)), tenant $TENANT_ID"

log "Registering resource providers (a few minutes on a new subscription)"
for ns in Microsoft.App Microsoft.ContainerRegistry Microsoft.KeyVault Microsoft.OperationalInsights \
  Microsoft.Insights Microsoft.AlertsManagement Microsoft.MachineLearningServices Microsoft.Storage \
  Microsoft.ManagedIdentity Microsoft.Consumption Microsoft.CostManagement; do
  state=$(az provider show -n "$ns" --query registrationState -o tsv 2>/dev/null || echo NotRegistered)
  if [[ "$state" != "Registered" ]]; then
    echo "  registering $ns"
    az provider register -n "$ns" --wait -o none
  else
    echo "  $ns already registered"
  fi
done

log "Resource groups"
az group create -n "$STATE_RG" -l "$LOCATION" --tags "${TAGS[@]}" purpose=tfstate -o none
az group create -n "$PROJECT_RG" -l "$LOCATION" --tags "${TAGS[@]}" env=prod -o none
PROJECT_RG_ID=$(az group show -n "$PROJECT_RG" --query id -o tsv)

log "Terraform state storage"
STATE_SA=$(az storage account list -g "$STATE_RG" --query "[?tags.purpose=='tfstate'].name | [0]" -o tsv)
if [[ -z "$STATE_SA" ]]; then
  STATE_SA="stdfcasttfstate$(tr -dc 'a-z0-9' </dev/urandom | head -c 5)"
  az storage account create -n "$STATE_SA" -g "$STATE_RG" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --allow-blob-public-access false --https-only true \
    --tags "${TAGS[@]}" purpose=tfstate -o none
fi
STATE_SA_ID=$(az storage account show -n "$STATE_SA" -g "$STATE_RG" --query id -o tsv)
az storage account blob-service-properties update --account-name "$STATE_SA" -g "$STATE_RG" \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 14 -o none
echo "  state account: $STATE_SA (versioning on)"

assign() { # principal-id principal-type role scope
  if [[ -z "$(az role assignment list --assignee "$1" --role "$3" --scope "$4" --query '[0].id' -o tsv)" ]]; then
    az role assignment create --assignee-object-id "$1" --assignee-principal-type "$2" \
      --role "$3" --scope "$4" -o none
    echo "  + $3"
  else
    echo "  = $3 (exists)"
  fi
}

log "Your data-plane access to the state account"
ME=$(az ad signed-in-user show --query id -o tsv)
assign "$ME" User "Storage Blob Data Contributor" "$STATE_SA_ID"
for i in {1..12}; do # role propagation
  if az storage container create -n tfstate --account-name "$STATE_SA" --auth-mode login -o none 2>/dev/null; then
    break
  fi
  echo "  waiting for role propagation ($i/12)"; sleep 10
done

log "GitHub Actions identity ($IDENTITY)"
az identity create -n "$IDENTITY" -g "$STATE_RG" -l "$LOCATION" --tags "${TAGS[@]}" -o none
CLIENT_ID=$(az identity show -n "$IDENTITY" -g "$STATE_RG" --query clientId -o tsv)
PRINCIPAL_ID=$(az identity show -n "$IDENTITY" -g "$STATE_RG" --query principalId -o tsv)

federate() { # name subject
  if ! az identity federated-credential show -n "$1" --identity-name "$IDENTITY" -g "$STATE_RG" -o none 2>/dev/null; then
    az identity federated-credential create -n "$1" --identity-name "$IDENTITY" -g "$STATE_RG" \
      --issuer "https://token.actions.githubusercontent.com" --subject "$2" \
      --audiences "api://AzureADTokenExchange" -o none
    echo "  + $2"
  else
    echo "  = $2 (exists)"
  fi
}
federate github-main "repo:${GITHUB_REPO}:ref:refs/heads/main"
federate github-pr "repo:${GITHUB_REPO}:pull_request"
federate github-env-production "repo:${GITHUB_REPO}:environment:production"

log "Role assignments for $IDENTITY"
sleep 20 # a new identity's service principal takes a moment to appear
assign "$PRINCIPAL_ID" ServicePrincipal "Contributor" "$PROJECT_RG_ID"
assign "$PRINCIPAL_ID" ServicePrincipal "User Access Administrator" "$PROJECT_RG_ID"
assign "$PRINCIPAL_ID" ServicePrincipal "Storage Blob Data Contributor" "$STATE_SA_ID"

cat <<EOF

==> Done. Set these as GitHub Actions *variables* (not secrets; none are credentials):

  gh variable set AZURE_CLIENT_ID       --body "$CLIENT_ID"
  gh variable set AZURE_TENANT_ID       --body "$TENANT_ID"
  gh variable set AZURE_SUBSCRIPTION_ID --body "$SUBSCRIPTION_ID"
  gh variable set TFSTATE_RG            --body "$STATE_RG"
  gh variable set TFSTATE_ACCOUNT       --body "$STATE_SA"
  gh variable set ALERT_EMAIL           --body "<your email>"

For local Terraform runs, create infra/envs/prod/backend.hcl:

  resource_group_name  = "$STATE_RG"
  storage_account_name = "$STATE_SA"
EOF
