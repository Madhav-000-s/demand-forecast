# Availability SLO: 5xx rate above 2%

**SLO:** 99.5% of `/v1` requests return non-5xx over 28 days.

## Triage

1. **Which revision?**
   ```kusto
   requests
   | where timestamp > ago(1h) and name has '/v1/'
   | summarize n=count(), errors=countif(toint(resultCode) >= 500) by application_Version, bin(timestamp, 5m)
   ```
2. **What error?**
   ```kusto
   exceptions | where timestamp > ago(1h) | summarize count() by type, outerMessage, application_Version
   ```
   Or the container logs:
   ```kusto
   ContainerAppConsoleLogs_CL | where TimeGenerated > ago(1h) | where Log_s has '"level": "ERROR"'
   ```
3. **503s only?** The model did not load (`/readyz` failing). Check the
   `model load failed` log line; usually bad artifacts in the image.

## Roll back

Reactivate the previous revision and send it all traffic:

```bash
az containerapp revision list -n $APP -g $RG --all -o table
az containerapp revision activate -n $APP -g $RG --revision <previous>
az containerapp ingress traffic set -n $APP -g $RG --revision-weight <previous>=100
```

Or re-run `deploy` with the previous model version from the registry.
Record the incident in `docs/postmortems/` if the error budget took a real hit.
