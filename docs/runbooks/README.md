# Runbooks

One page per alert. Each alert's description links here. The workbook
(Application Insights > Workbooks > "dfcast: SLOs, canaries and drift") is the
first place to look for any of them.

| Alert | Severity | Runbook |
|---|---|---|
| Forecast p95 latency above 300 ms | 2 | [latency.md](latency.md) |
| Forecast 5xx rate above 2% | 1 | [errors.md](errors.md) |
| More than 3 replica restarts in 15 min | 2 | [restarts.md](restarts.md) |
| /healthz failing from 2+ locations | 1 | [availability.md](availability.md) |
| Input drift: feature PSI above 0.25 | 3 | [drift.md](drift.md) |
| Budget threshold reached | email | [budget.md](budget.md) |

Shell snippets assume:

```bash
RG=rg-dfcast-prod-cin
APP=ca-dfcast-prod-cin
az containerapp revision list -n $APP -g $RG -o table   # which revisions take traffic
```
