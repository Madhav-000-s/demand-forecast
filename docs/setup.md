# Setup: from an empty subscription to a live canary pipeline

Everything after step 2 runs from GitHub Actions. Steps marked **(you)** need
your Azure or GitHub login.

## 1. Bootstrap Azure (you, once)

In [Azure Cloud Shell](https://shell.azure.com) (switch it to **Bash**):

```bash
gh auth login                                   # Cloud Shell ships gh
gh repo clone Madhav-000-s/demand-forecast && cd demand-forecast
bash infra/bootstrap/bootstrap.sh
```

It registers resource providers, creates the state storage and
`rg-dfcast-prod-cin`, and creates `id-dfcast-github-cin`, a managed identity that
GitHub Actions logs in as with OIDC (no secrets). It prints the next commands.

## 2. GitHub settings (you, once)

Run the `gh variable set ...` lines the script printed, plus:

```bash
gh variable set ALERT_EMAIL --body "<your email>"
```

Create the `production` environment (Settings > Environments). Branch protection
on `main` (Settings > Branches): require a pull request, the `pr` checks, and
CODEOWNERS review. Private repos need GitHub Pro (free with the Student Pack)
for this.

## 3. First infrastructure apply

```bash
gh workflow run infra.yml && gh run watch
```

Creates everything except the Container App (no image exists yet): Log
Analytics, App Insights, action group, registry, Key Vault, Azure ML workspace
and cluster, budget.

Check the Azure ML vCPU quota for the cluster's VM family now: Azure ML studio >
Compute > Quotas (or `az ml compute list-usage` with the `ml` extension). The
default cluster needs 2 vCPUs of the DSv2 family in Central India. If the limit
is lower, set `aml_vm_size` to a family that has quota.

## 4. Register the dataset (you, once)

From the project folder on your laptop (Azure CLI + `az extension add -n ml`):

```bash
az ml data create -g rg-dfcast-prod-cin -w mlw-dfcast-prod-cin \
  --name store-item-sales --version 1 --type uri_file \
  --path data/raw/train.csv \
  --description "Kaggle Store Item Demand Forecasting train.csv (2013-2017, 10 stores x 50 items)"
```

## 5. Train, register, build the first image

```bash
gh workflow run train.yml -f reason="first model" && gh run watch
```

Azure ML trains, the promotion gate checks the baseline, and the model is
registered as `dfcast-lgbm:1`. Its deploy step builds and pushes the image and,
because no app exists yet, prints the `APP_IMAGE` value in the run summary.

## 6. Create the app

```bash
gh variable set APP_IMAGE --body "<value from the run summary>"
gh workflow run infra.yml && gh run watch
```

Terraform creates the Container Apps environment, the app (first revision =
that image) and the SLO alerts. The app URL is in the run summary.

## 7. Every release after that

- Code change to the API: merge a PR, and `deploy` runs a 10% canary.
- Model change: merge a PR touching `ml/`, or `gh workflow run train.yml`.
  `train` then runs the gate, registers the model and calls `deploy`.
- Infra change: merge a PR touching `infra/`, and `infra` applies it. PRs show
  the plan as a comment.

## 8. Monitoring and drift (automatic)

- **Dashboard:** Azure portal > Application Insights `appi-dfcast-prod-cin` >
  Workbooks > "dfcast: SLOs, canaries and drift". Created by Terraform.
- **Drift job:** `drift` runs every 6 hours on its own (GitHub runs scheduled
  workflows from `main`). Run it on demand with
  `gh workflow run drift.yml -f hours=6 -f retrain=false`. With too little
  traffic it reports `insufficient_data`, which is normal for a demo service.
- **Drift alert:** emails when the drift job reports drift; see
  [runbooks/drift.md](runbooks/drift.md).

**Rate limit.** The API allows 10 requests/s per client IP (bursts of 50, per
replica; `rate_limit_rps` / `rate_limit_burst` in the container_app module).
Terraform generates an ops bypass token into Key Vault (`ops-bypass-token`);
the deploy and drill workflows read it and send it as `X-Ops-Token`, so canary
analysis, smoke tests and k6 are not throttled. Template changes create a
revision at 0% traffic, so run `gh workflow run deploy.yml` after an infra
change to the app.

## Local Terraform (optional)

```bash
cd infra/envs/prod
cp backend.hcl.example backend.hcl    # fill in from the bootstrap output
az login
terraform init -backend-config=backend.hcl
TF_VAR_alert_email=you@example.com terraform plan
```
