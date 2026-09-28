# alerts

| Alert | Condition | Sev |
|---|---|---|
| Latency | p95 of `/v1` requests > 300 ms over the window (min 20 requests) | 2 |
| Errors | 5xx > 2% of `/v1` requests over the window (min 20 requests) | 1 |
| Restarts | > 3 replica restarts in 15 min | 2 |
| Availability (optional) | `/healthz` web test failing from >= 2 of 3 locations | 1 |
| Budget | $25 / $50 / $75 actual spend, 100% forecast | email |

Log alerts default to a 15-minute cadence, the cheapest tier. Switch
`evaluation_frequency` to `PT5M` while demoing. The drift alert is added with the
drift job (milestone 5).
