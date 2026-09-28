# More than 3 replica restarts in 15 minutes

Liveness probe failures (`/healthz`, 3 x 15 s) or crashes restart replicas.

1. Container logs around the restarts:
   ```kusto
   ContainerAppSystemLogs_CL | where TimeGenerated > ago(1h) | project TimeGenerated, RevisionName_s, Reason_s, Log_s
   ```
2. `OOMKilled`: raise `memory` in the container_app module (default 1Gi).
3. Crash on start: startup probe gives the model 2 minutes to load; a crash loop
   usually means missing artifacts or a dependency error. Roll back
   (see [errors.md](errors.md#roll-back)).
4. During a chaos drill this alert is expected; note the timestamps for the postmortem.
