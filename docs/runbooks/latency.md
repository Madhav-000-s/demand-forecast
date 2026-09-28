# Latency SLO: p95 above 300 ms

**SLO:** 99% of `/v1/forecast*` requests under 300 ms over 28 days. The alert fires
when p95 over the evaluation window exceeds 300 ms with at least 20 requests.

## Triage (5 minutes)

1. **Was there a deploy?** Check the App Insights annotations and the latest
   `deploy` run. If a canary is running, the canary analysis will roll it back on
   its own; watch the run.
2. **Cold starts?** With `min_replicas = 0`, the first requests after idle wait for
   a replica. In App Insights:
   ```kusto
   requests
   | where timestamp > ago(1h) and name has '/v1/'
   | summarize p50=percentile(duration,50), p95=percentile(duration,95), n=count() by bin(timestamp, 5m), application_Version
   ```
   A single spike right after a quiet period is a cold start. Sustained high p95 is not.
3. **Load?** Check replica count (Container App > Metrics > Replica Count). If it is
   pinned at `max_replicas` (3), the app is saturated.
4. **Batch requests?** `/v1/forecast/batch` with 50 series x 90 days is heavier:
   split latency by `name`.

## Mitigate

- Saturated: raise `max_replicas` in `infra/modules/container_app` (PR), or lower
  the HTTP scale threshold so it scales out earlier.
- Cold starts during a demo: set GitHub variable `MIN_REPLICAS=1` and run the
  `infra` workflow.
- Regression after a deploy: roll back (see [errors.md](errors.md#roll-back)).
