# dashboard

Azure Monitor workbook attached to Application Insights (Portal: Application
Insights > Workbooks > "dfcast: SLOs, canaries and drift").

| Panel | Source |
|---|---|
| SLOs over 28 days, error budget left | `requests` |
| Burn rate over 1 h / 6 h / 24 h / 3 d | `requests` |
| Latency p50/p95/p99 vs 300 ms, 5xx rate | `requests` |
| Traffic by revision (canary splits) and by source | `requests`, `traces` |
| Mean predicted units by model, horizon mix | `customMetrics` (OpenTelemetry) |
| Drift history, PSI per feature, drift job runs | `customEvents` (`drift_check`) |
| Chaos drills: expectation, outcome, duration | `customEvents` (`drill`) |
| Replica starts with model load time, recent 5xx | `traces`, `requests` |

Each query is a file in `queries/`; paste one into App Insights > Logs to run
it on its own (replace `{TimeRange:grain}` with e.g. `5m`).
