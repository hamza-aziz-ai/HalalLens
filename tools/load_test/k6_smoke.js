import http from "k6/http";
import { check, sleep } from "k6";

const API_BASE = __ENV.API_BASE || "https://api.halallens.ai";
const SYMBOL = __ENV.SYMBOL || "TCS";

export const options = {
  vus: Number(__ENV.VUS || 100),
  duration: __ENV.DURATION || "60s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export default function () {
  const health = http.get(`${API_BASE}/health`);
  check(health, { "health ok": (res) => res.status === 200 });

  const recent = http.get(`${API_BASE}/filings/recent?limit=10`);
  check(recent, { "recent ok": (res) => res.status === 200 });

  const filing = http.get(`${API_BASE}/filings/${SYMBOL}`);
  check(filing, { "filing ok": (res) => res.status === 200 || res.status === 404 });

  sleep(1);
}
