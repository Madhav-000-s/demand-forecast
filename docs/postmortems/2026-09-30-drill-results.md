# Chaos drills, 2026-09-30: results and findings

Five drills against production, each with a written expectation
([docs/drills.md](../drills.md)). Numbers are from the drill records
(App Insights `drill` events) and workflow logs.

| Drill | Expected | Outcome | Verdict |
|---|---|---|---|
| `bad-model` | Smoke test rejects wrong forecasts before any traffic | 20/20 reference requests off by 4.1-18.2 units (tolerance 0.02); rolled back 1 min 46 s after the canary revision was created; 0 user requests served | passed |
| `slow-release` (+400 ms) | Canary analysis rolls back on p95 > 300 ms | Smoke test passed (it checks correctness, not speed); after the 10% shift, p95 406 ms then 414 ms; rollback decided 3 min 07 s after the shift, 43 canary requests affected | passed |
| `drift` (800 skewed requests) | Drift job reports drift on store/item | status `drift`: PSI store 6.81, item 6.81, all six history features 0.62-1.29 | passed |
| `load` (k6, 100 VUs) | Server p95 < 300 ms, < 1% errors | p95 **1,348 ms** at ~45 req/s, 2 replicas | **failed**, see [postmortem](2026-09-30-load-drill-latency.md) |
| `load` re-run after fix | same | p95 17 ms, p99 87 ms at 73.5 req/s, 5 replicas, 0 5xx | passed |
| `restart` | < 1% of requests fail during a revision restart | 4 of 688 failed (0.58%), 0 server 5xx, slowest 8.4 s | passed |

## Findings beyond the drill verdicts

1. **Request telemetry was undercounted.** The Azure Monitor OpenTelemetry
   distro samples request traces (rate-limited, ~5/s by default). The drift
   drill sent 800 requests; App Insights stored 133 rows, each carrying
   `itemCount`. Every query counted rows with `count()`, so alerts,
   dashboard, canary minimums and drill stats undercounted under load. Fixed
   in PR #6 (`sum(itemCount)` everywhere, with a test guarding it). Logs are
   not sampled, which is why the drift job still saw all 800.
2. **Deploy annotations had never worked.** The App Insights Annotations API
   wants one object with an `Id`; `deploy.yml` sent an array. The step was
   `continue-on-error`, so every deploy since the first silently skipped its
   annotation. Found in the `bad-model` run log; fixed in PR #6 and confirmed
   on the next deploy.
3. **Canary detection is bounded by telemetry delay.** In `slow-release`,
   minutes 1 and 2 of the analysis showed identical counts: App Insights data
   arrives 1-2 minutes late, and the analysis also waits for 30 canary
   requests. At real traffic levels a 10% canary takes longer to judge.
4. **Drills and deploys could overlap.** Fixed: drill traffic jobs now take
   the `deploy-prod` concurrency lock.
