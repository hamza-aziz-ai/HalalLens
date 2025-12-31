import http from "k6/http";
import { check, sleep } from "k6";

const API_BASE = __ENV.API_BASE || "https://api.halallens.ai";
const SYMBOL = __ENV.SYMBOL || "TCS";
const EMAIL = __ENV.AUTH_EMAIL || "loadtest@halallens.ai";
const PASSWORD = __ENV.AUTH_PASSWORD || "LoadTest123!";
const TRIAL_PLAN = __ENV.TRIAL_PLAN || "starter";

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURATION || "60s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1500"],
  },
};

const authParams = {
  headers: { "Content-Type": "application/json" },
};

const narrationPayload = JSON.stringify({
  snapshot: {
    symbol: SYMBOL,
    filing_date: "2024-06-30",
    total_debt: 25000000,
    cash_equiv: 10000000,
    revenue: 200000000,
    non_permissible_income: 5000000,
    accounts_receivable: 12000000,
    liquid_assets: 6000000,
  },
  market_data: { market_cap: 400000000 },
});

export function setup() {
  const register = http.post(
    `${API_BASE}/auth/register`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    authParams,
  );
  if (![200, 409].includes(register.status)) {
    throw new Error(`register failed: ${register.status} ${register.body}`);
  }

  const login = http.post(
    `${API_BASE}/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    authParams,
  );
  if (login.status !== 200) {
    throw new Error(`login failed: ${login.status} ${login.body}`);
  }
  const data = login.json();
  const trial = http.post(
    `${API_BASE}/billing/trial`,
    JSON.stringify({ plan_code: TRIAL_PLAN }),
    {
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${data.token}`,
      },
    },
  );
  if (trial.status !== 200) {
    throw new Error(`trial failed: ${trial.status} ${trial.body}`);
  }
  return { token: data.token };
}

export default function (data) {
  const headers = {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${data.token}`,
    },
  };

  const health = http.get(`${API_BASE}/health`);
  check(health, { "health ok": (res) => res.status === 200 });

  const recent = http.get(`${API_BASE}/filings/recent?limit=10`);
  check(recent, { "recent ok": (res) => res.status === 200 });

  const history = http.get(
    `${API_BASE}/filings/${SYMBOL}/history?limit=10`,
    headers,
  );
  check(history, { "history ok": (res) => res.status === 200 });

  const narration = http.post(
    `${API_BASE}/narrate`,
    narrationPayload,
    headers,
  );
  check(narration, { "narrate ok": (res) => res.status === 200 });

  sleep(1);
}
