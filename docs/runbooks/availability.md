# /healthz failing from 2 or more locations

The availability test is off by default (`enable_availability_test`) because
probes cost money and keep a replica awake. When it is on and fires:

1. `curl -i https://<fqdn>/healthz` from your machine.
2. Container App > Revisions: is any revision active with traffic?
3. If the environment itself is down, check Azure status for Central India and
   the subscription state (Azure for Students disables resources when credit runs out:
   see [budget.md](budget.md)).
