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
- HTTP scaling on concurrent requests (prod: 1 vCPU replicas, scale at 10
  in-flight requests, 0-5 replicas; sized by the 2026-09-30 load drill).
- Per-client rate limit settings (`RATE_LIMIT_RPS`, `RATE_LIMIT_BURST`) and the
  ops bypass token (Key Vault reference) are passed as environment variables.
- Changes to the template create a new revision at 0% traffic (deploys pin
  traffic to named revisions); run `deploy` afterwards to roll it out.
- `image`, `revision_suffix` and the traffic split are ignored after creation:
  releases are made by deploy.yml, not by Terraform.
