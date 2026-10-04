# Budget threshold reached

Alerts at 25 / 50 / 75 % of the annual budget (actual spend) and when the
forecast crosses 100 %. The budget is in the billing currency: ₹9,600 (~$100),
so alerts fire near ₹2,400 / ₹4,800 / ₹7,200.
There is no card on file, so running out of credit disables the resources.

1. Cost Management > Cost analysis, group by resource.
2. Usual suspects: Log Analytics ingestion (daily cap is 0.5 GB), `min_replicas=1`
   left on, the availability test, Azure ML compute not scaling to zero.
3. Cut: set `MIN_REPLICAS=0`, disable the availability test, lower the log cap.
4. After the application season: `terraform destroy`.
