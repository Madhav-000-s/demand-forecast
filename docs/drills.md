# Chaos drills

Drills break production on purpose, in a controlled way, to prove that the
safety nets work and to measure how the service behaves. Each drill has a
written expectation, runs from one workflow, and records its result as a
`drill` event in App Insights (workbook panel "Chaos drills") with the numbers
a postmortem needs.

```bash
gh workflow run drill.yml -f drill=<name>          # drift also takes -f retrain=true
gh run watch
```

| Drill | What it does | Expected | Safety net under test |
|---|---|---|---|
| `bad-model` | Releases an image whose sales history is scaled x1.3: the model loads, answers HTTP 200, and every forecast is ~30% high | Smoke test rejects the canary before any traffic shift; rollback | Smoke test's comparison with training output (`canary_reference.json`) |
| `slow-release` | Releases an image with `fault.json` adding 400 ms to every `/v1` request | Canary analysis sees p95 > 300 ms on the 10% canary and rolls back | Canary analysis (App Insights, canary revision only) |
| `drift` | Sends 800 requests for stores 1-2 and items 1-5 only | Drift job reports `drift` on store/item; drift alert emails; retrain only with `retrain=true` (24 h cooldown) | Drift job, drift alert |
| `load` | k6 from the GitHub runner: 20 virtual users, then a spike to 100 | Server p95 < 300 ms, < 1% errors, replicas scale out | Autoscaling, latency SLO |
| `restart` | Restarts the serving revision while 5 req/s flow | < 1% of requests fail while replicas come back | Probes, replica restart behaviour |

How faults are injected: release drills go through the real `deploy.yml`
with a `drill` flag. The fault is baked into the drill image (a scaled
`history.npz`, or an extra `fault.json` layer); production images never
contain `fault.json`, so no setting can turn a fault on in a normal release.
A drill release is never promoted: it always rolls back, and the deploy job
fails only if the fault got past both checks.

Drill traffic is tagged `X-Traffic-Source: drill` (k6: `load`). The drift
drill counts it on purpose; canary and smoke traffic are always excluded from
drift statistics.

Client-side latency from GitHub runners includes the network path to Central
India (~200+ ms). SLO numbers come from App Insights (server-side request
duration), which the drill record reports separately.

After a drill, write a postmortem from its record: [postmortems/](postmortems/).
