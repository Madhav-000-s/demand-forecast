// Load drill: ramp to a steady load, then a spike, against the public URL.
//   docker run --rm -v "$PWD/scripts/k6:/scripts" -w /scripts -e BASE_URL=https://<fqdn> \
//     grafana/k6:2.3.0 run load.js
// Requests are tagged X-Traffic-Source: load (kept out of drift statistics).
// Client-side latency includes the network path from the runner to Central
// India; the server-side SLO numbers come from App Insights afterwards.
import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL;
const STEADY_VUS = Number(__ENV.STEADY_VUS || 20);
const SPIKE_VUS = Number(__ENV.SPIKE_VUS || 100);

export const options = {
  stages: [
    { duration: "30s", target: STEADY_VUS },
    { duration: "2m", target: STEADY_VUS },
    { duration: "30s", target: SPIKE_VUS },
    { duration: "2m", target: SPIKE_VUS },
    { duration: "30s", target: 0 },
  ],
  thresholds: {
    http_req_failed: ["rate<0.01"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(95)", "p(99)", "max"],
};

const HORIZONS = [7, 14, 30, 90];

function body() {
  const horizon = HORIZONS[Math.floor(Math.random() * HORIZONS.length)];
  const offset = Math.floor(Math.random() * (91 - horizon + 1));
  const start = new Date(Date.UTC(2018, 0, 1) + offset * 86400000).toISOString().slice(0, 10);
  return JSON.stringify({
    store: 1 + Math.floor(Math.random() * 10),
    item: 1 + Math.floor(Math.random() * 50),
    start_date: start,
    horizon_days: horizon,
  });
}

export default function () {
  const res = http.post(`${BASE_URL}/v1/forecast`, body(), {
    headers: Object.assign(
      { "content-type": "application/json", "x-traffic-source": "load" },
      __ENV.OPS_TOKEN ? { "x-ops-token": __ENV.OPS_TOKEN } : {},
    ),
    timeout: "30s",
  });
  check(res, { "status 200": (r) => r.status === 200 });
  sleep(0.5);
}

export function handleSummary(data) {
  return { "k6-summary.json": JSON.stringify(data, null, 2) };
}
