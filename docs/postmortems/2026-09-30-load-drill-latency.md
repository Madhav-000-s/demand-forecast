# Load drill: p95 latency 1.35 s under a 100-user spike (SLO 300 ms)

| | |
|---|---|
| Date | 2026-09-30, 17:10-17:16 UTC (fault), fix verified 23:13-23:18 UTC |
| Type | Drill (`drill.yml`, `load`), no real users affected |
| Severity | SEV3: synthetic traffic only; the same load from users would have breached the latency SLO |
| Detection | Drill verdict (server p95 from App Insights), same run |
| Time to mitigate | ~6 h (analysis, fix PR #7, canary rollout, re-run) |
| User impact | None (drill traffic). Under real traffic: ~3 minutes with p95 above 1.4 s |
| Links | [failed run](https://github.com/Madhav-000-s/demand-forecast/actions/runs/36749393510), [timeline report](https://github.com/Madhav-000-s/demand-forecast/actions/runs/36763693007), [fix PR #7](https://github.com/Madhav-000-s/demand-forecast/pull/7), [passing re-run](https://github.com/Madhav-000-s/demand-forecast/actions/runs/36789820416) |

## Summary

k6 ramped to 20 virtual users and then spiked to 100 against the production
API. One replica with 0.5 vCPU served ~29 requests/s at p95 16 ms, then
saturated at ~42 requests/s: p95 rose to 1.4 s. The scale rule (add a replica
at 50 concurrent requests) fired only after the queue had built, and the
second replica started about 75 seconds after saturation began. Two half-core
replicas still missed the SLO at ~95 requests/s. Resizing to 1 vCPU and
scaling at 10 concurrent requests brought p95 to 17 ms at 73.5 requests/s in
the re-run.

## Timeline (UTC)

| Time | Event |
|---|---|
| 17:10:49 | k6 starts; the app is scaled to zero |
| 17:11:08 | First replica loads the model (0.045 s); the container start took ~19 s |
| 17:11:19-17:11:33 | 10 requests sent before the replica was ready time out at k6's 30 s limit |
| 17:12 | 1,724 requests (~29/s), p95 16 ms, 1 replica |
| 17:13 | Spike: 2,503 requests (~42/s), p95 **1,409 ms**, still 1 replica |
| 17:14:13 | Second replica starts (~75 s after saturation) |
| 17:14-17:15 | p95 1,743 ms then 697 ms at up to ~95 requests/s on 2 replicas |
| 17:19:30 | Drill records FAILED: server p95 1,348 ms, p99 1,752 ms, 0 5xx |
| 19:09 | `drill report` pulls the per-minute timeline above from App Insights |
| 19:22 | PR #7 merged: 1 vCPU / 2 GiB replicas, scale at 10 concurrent requests, max 5 |
| 19:27-19:39 | New size released through the canary (0% 5xx, p95 15 ms), promoted |
| 23:13-23:18 | Re-run PASSED: server p95 17 ms, p99 87 ms over 24,037 requests, 5 replicas |

## What happened

Evidence: `drill report` for 17:09-17:20 (requests weighted by `itemCount`):

| minute | requests | p50 ms | p95 ms | replicas |
|---|---|---|---|---|
| 17:11 | 705 | 12 | 89 | 1 |
| 17:12 | 1,724 | 7 | 16 | 1 |
| 17:13 | 2,503 | 422 | 1,409 | 1 |
| 17:14 | 3,357 | 608 | 1,743 | 2 |
| 17:15 | 5,693 | 300 | 697 | 2 |
| 17:16 | 1,026 | 6 | 13 | 2 |

A forecast costs roughly 7-15 ms of CPU (server p50/p95 at low load). The API
runs one uvicorn worker, so a replica can use at most one core, and it had
half of one: saturation at ~40 requests/s matches that budget. The HTTP scale
rule counts concurrent requests per replica; with 7 ms responses it takes a
queue of seconds to reach 50 in flight, so scale-out started only once users
were already waiting.

Re-run after the fix (23:13-23:18):

| minute | requests | p50 ms | p95 ms | replicas |
|---|---|---|---|---|
| 23:13 | 292 | 84 | 141 | 1 |
| 23:14 | 1,785 | 7 | 18 | 4 |
| 23:15 | 2,695 | 6 | 14.5 | 4 |
| 23:16 | 7,795 | 7 | 17 | 5 |
| 23:17 | 8,354 | 7 | 16 | 5 |
| 23:18 | 3,116 | 7 | 17 | 5 |

Replicas started at 23:13:27, 23:13:46, 23:14:17, 23:14:18 and 23:16:21.

## What went well

- The drill had a written expectation and failed loudly on the server-side
  number the SLO is defined on, not on the client number (which includes
  ~200 ms of network from the GitHub runner to Central India).
- Zero 5xx throughout: the service slowed down but never errored.
- The per-minute report made the cause obvious before any change was made,
  and the fix shipped through the same canary path as any release.

## What went wrong / surprised us

- **Sizing was a guess.** 0.5 vCPU and a 50-request scale rule were defaults
  chosen before any load test.
- **Cold start.** With scale-to-zero, the first requests after idle wait for a
  container start (~19-25 s here; the model itself loads in 0.05 s). 10 and 9
  requests timed out in the two runs (0.07% and 0.04%).
- **A drill ran during a deploy.** The re-run was first started while a canary
  was in progress; it was cancelled. Nothing stopped the two from overlapping.

## Action items

| Action | Type | Status |
|---|---|---|
| 1 vCPU / 2 GiB replicas, scale at 10 concurrent requests, max 5 (PR #7) | mitigate | done |
| Plan-time Terraform test pins the sizing | prevent | done |
| `drill report`: per-minute telemetry for any window | detect | done |
| Drill traffic jobs share the `deploy-prod` lock with deploys | prevent | done (this PR) |
| `MIN_REPLICAS=1` during demo windows to remove cold starts (one replica billed around the clock; check the cost in Cost Management first) | mitigate | open, operator choice |
| Revisit if the model or horizon grows: per-request CPU sets the capacity per replica | prevent | open |
