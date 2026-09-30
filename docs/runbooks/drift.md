# Input drift: feature PSI above 0.25

**What fired:** the `drift` workflow (every 6 h) compared the features of recent
requests with the reference distribution of the model that served them and
found at least one monitored feature with PSI above 0.25, on 500 or more
requests. Synthetic deploy traffic (`X-Traffic-Source: canary` / `smoke`) is
not counted.

**What already happened automatically:** unless `train.yml` ran in the last
24 hours, the drift job started it. That run trains, applies the promotion
gate and, if the candidate passes, releases it through the canary deploy. The
alert is informational (severity 3); it resolves on the next clean check.

## Triage

1. **Which feature, how far?** Open the drift job run (link in the
   `drift_check` event and in the workbook's "Drift job runs" panel), or:
   ```kusto
   customEvents
   | where name == 'drift_check'
   | top 5 by timestamp desc
   | project timestamp, status = tostring(customDimensions.status),
             feature = tostring(customDimensions.max_feature),
             max_psi = todouble(customMeasurements.max_psi),
             samples = toint(customMeasurements.samples)
   ```
2. **Real users or a test?** Break recent requests down by source:
   ```kusto
   traces
   | where timestamp > ago(6h) and message == 'forecast_features'
   | summarize n = count() by source = tostring(customDimensions.traffic_source)
   ```
   A drill (`drill`) or a load test explains drift by design.
3. **What shifted?** For `store` / `item`, compare the request mix:
   ```kusto
   traces
   | where timestamp > ago(6h) and message == 'forecast_features'
   | summarize n = count() by store = toint(customDimensions.store)
   | order by n desc
   ```
   For history features (`lag_91`, `roll91_mean_91`, ...), a shift with a normal
   store/item mix means requests are concentrated on unusual dates or series.
4. **Is accuracy affected?** Drift in inputs is not a drop in accuracy by
   itself. Check the workbook's "Mean predicted units" panel for a step change,
   and whether the retrained candidate passed the gate.

## Decide

| Finding | Action |
|---|---|
| Drill or load test | Nothing; note it on the drill record |
| Real change in who asks for what, gate passed | Let the canary release finish |
| Gate failed (candidate worse) | Keep the current model; investigate data before retraining again |
| Retraining skipped by the cooldown | Re-run `train.yml` manually once the cause is understood |

## Honest limits

The training data is the static Kaggle dataset, so a retrain here produces
the same model with a new version label; it exercises the gate and the canary,
it cannot learn new behaviour. With a live data feed the same path would
retrain on fresh history.

Thresholds: `PSI_THRESHOLD` and `MIN_SAMPLES` in `.github/workflows/drift.yml`
(0.25 and 500; below 500 requests a 50-category feature shows PSI around 0.1
to 0.3 from sampling noise alone).
