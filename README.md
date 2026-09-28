# dfcast: demand forecasting service on Azure

A store-item demand forecasting API, run the way a production team would run it:
provisioned with Terraform, shipped by GitHub Actions, watched with Application
Insights dashboards and alerts, and held to written SLOs. The model is deliberately
simple; the platform around it is the point.

> Status: **Milestones 1-2 done**: model, API, Terraform and GitHub Actions
> workflows. Next: Azure accounts and identity, then the first deploy
> ([docs/setup.md](docs/setup.md)).

## Model

One global LightGBM model forecasts daily unit sales for all 500 store-item series
(10 stores x 50 items, Kaggle *Store Item Demand Forecasting*) up to 91 days ahead.
Every history feature is lagged by at least 91 days, so any day in the horizon is
predicted directly, never recursively.

| Feature group | Features |
|---|---|
| Identity | `store`, `item` (categorical) |
| Calendar | day of week, day of month, month, ISO week, day of year, year, weekend flag |
| History (lag >= 91 days) | sales 91 and 364 days back; 28-day mean and std and 91-day mean ending 91 days back; same-weekday mean over the prior year |

**Evaluation is honest about the lag.** For validation and test, history after the
forecast origin is hidden, and each window is the 91 days a real forecast from that
origin could serve. The shipped model is the one the test numbers describe
(trained through 2017-09-30 with the round count chosen on validation).

Test window 2017-10-01 to 2017-12-30, all 500 series (45,500 predictions):

| Model | SMAPE | MAE |
|---|---|---|
| **LightGBM** | **12.36** | **5.87** |
| Seasonal naive (same weekday last year) | 17.84 | 8.35 |
| 28-day moving average | 22.51 | 11.92 |

A **promotion gate** (`ml/gate.py`) only releases a model whose test SMAPE beats
seasonal naive and is no more than 2% worse than the model in production.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/forecast` | Forecast one store-item pair |
| POST | `/v1/forecast/batch` | Up to 50 pairs per call |
| GET | `/v1/model` | Model version, git SHA, test metrics, servable date range |
| GET | `/healthz` | Liveness |
| GET | `/readyz` | Readiness: model loaded and warm-up prediction succeeded |
| GET | `/docs` | OpenAPI UI |

```http
POST /v1/forecast
{ "store": 3, "item": 17, "start_date": "2018-01-01", "horizon_days": 7 }
```

```json
{
  "store": 3, "item": 17, "model_version": "20260928.1122-abc1234",
  "forecast": [ { "date": "2018-01-01", "units": 22.99 }, "..." ]
}
```

Bad input returns 422 with the offending field; forecast dates must fall inside the
window the shipped history supports (reported by `/v1/model`). Every response carries
`X-Request-ID` and `X-Model-Version`. Each forecast writes one JSON log line with its
input features, which the drift job compares against `reference_stats.json`.

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements/dev.txt

# data/raw/train.csv from Kaggle (not committed)
python -m ml.train --data data/raw/train.csv --out artifacts
python -m ml.gate --candidate artifacts/metrics.json

uvicorn app.main:app --reload            # http://localhost:8000/docs
pytest                                    # unit + API contract tests (synthetic data, no CSV needed)
ruff check . && ruff format --check . && mypy app ml scripts
```

Docker (artifacts are baked into the image, so one tag pins one model):

```bash
docker build -t dfcast:dev .
docker run --rm -p 8000:8000 dfcast:dev
```

## Platform

```
GitHub (PR) ── pr.yml: ruff · mypy · pytest+coverage · terraform fmt/validate/plan · Checkov · Trivy · SonarCloud
   │ merge
   ├─ infra.yml ── terraform apply (OIDC, no secrets) ──► Azure (Central India)
   ├─ train.yml ── Azure ML command job ─► promotion gate ─► model registry (dfcast-lgbm:N)
   │                                                            │
   └─ deploy.yml ◄──────────────────────────────────────────────┘
        build image with model N ─► ACR ─► Container Apps revision at 0%
        ─► smoke test on the canary label URL ─► 10% traffic ─► 10-min analysis
           (App Insights: canary 5xx rate and p95) ─► promote to 100% or roll back
```

| Azure resource | Purpose |
|---|---|
| Container Apps (multiple-revision mode, 0-3 replicas) | API hosting, canary traffic splitting |
| Container Registry (Basic) | Images, pulled by the app's managed identity |
| Azure Machine Learning (workspace, 0-1 node CPU cluster, model registry) | Training jobs and model versions |
| Log Analytics + Application Insights (OpenTelemetry) | Traces, logs, SLO queries |
| Key Vault (RBAC) | App secrets, read via managed identity |
| Monitor alerts + action group, budget | Latency / 5xx SLO alerts, restarts, $25/$50/$75 spend |

Each alert links to a runbook in [docs/runbooks](docs/runbooks). Every PR uses
a template with a risk level and rollback plan; `main` requires review
(CODEOWNERS) and green checks.

### Canary safety checks

Training writes `canary_reference.json`: 20 fixed requests with the predictions
the model produced and the seasonal-naive values for the same days. Before a new
revision gets any traffic, the smoke test requires its answers to match the
training output (so the image contains the model we think it does) and to stay
within SMAPE 35 of seasonal naive. The real model scores 13.7; a constant model
scores 53. A model that returns plausible-looking nonsense with HTTP 200 is
stopped here, not by users.

## Repository layout

```
app/              FastAPI service, model loading, JSON logs, OpenTelemetry
ml/               features (shared with the API), training, metrics, promotion gate,
                  drift statistics, canary reference; ml/aml/ = Azure ML job spec
scripts/          post-deploy smoke test, canary analysis
tests/            unit and API contract tests (synthetic data)
infra/bootstrap/  one-time script: providers, state storage, GitHub OIDC identity
infra/modules/    observability, registry, keyvault, container_app, alerts, azureml
infra/envs/prod/  root configuration and remote-state backend
.github/          workflows, PR template, CODEOWNERS, Dependabot
docs/             setup guide, runbooks
```

## Roadmap

1. ~~Model and API~~
2. ~~Terraform (Container Apps, ACR, Key Vault, App Insights, Azure ML) and GitHub Actions workflows~~
3. Accounts and identity (OIDC, state storage, SonarCloud)
4. First deploy
5. Observability dashboards, SLO alerts, canary deploys with automated rollback, drift-triggered retraining
6. Chaos drills and a postmortem written from real telemetry
7. Portfolio polish
