# container_app

Container Apps environment and the forecast API app, plus the app's user-assigned
managed identity (AcrPull on the registry, Key Vault Secrets User on the vault).

- Standard environment created through AzAPI with `environmentMode =
  WorkloadProfiles` (API 2026-07-01) and the serverless `Consumption` profile.
  azurerm cannot set the mode, and Azure then defaults to *express*, which lacks
  revisions, traffic splitting, labels, managed identity, Key Vault references
  and probes. A postcondition fails the apply if Azure reports another mode.
- Multiple-revision mode so deploy.yml can run 10% canaries.
- Startup/readiness probes on `/readyz`, liveness on `/healthz`.
- HTTP scaling at 50 concurrent requests, 0-3 replicas by default.
- `image`, `revision_suffix` and the traffic split are ignored after creation:
  releases are made by deploy.yml, not by Terraform.
