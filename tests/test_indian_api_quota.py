"""The Indian Stock API plan is small (500 requests/month on the free plan), so
every vendor call goes through a monthly cap, and the key never goes in a URL."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import market_data.indian_api as indian_api

MONTH = datetime.now(timezone.utc).strftime("%Y-%m")


def test_no_limit_allows_and_writes_nothing(tmp_path):
    path = tmp_path / "quota.json"
    assert indian_api._consume_quota(limit=0, path=str(path))
    assert not path.exists()


def test_limit_is_enforced_and_persisted(tmp_path):
    path = str(tmp_path / "quota.json")
    assert [indian_api._consume_quota(limit=2, path=path) for _ in range(3)] == [True, True, False]
    assert json.loads(open(path, encoding="utf-8").read()) == {MONTH: 2}


def test_new_month_starts_from_zero(tmp_path):
    path = tmp_path / "quota.json"
    path.write_text(json.dumps({"2000-01": 999}), encoding="utf-8")
    assert indian_api._consume_quota(limit=5, path=str(path))
    assert json.loads(path.read_text(encoding="utf-8")) == {MONTH: 1}


def test_corrupt_counter_file_is_reset(tmp_path):
    path = tmp_path / "quota.json"
    path.write_text("not json", encoding="utf-8")
    assert indian_api._consume_quota(limit=5, path=str(path))
    assert json.loads(path.read_text(encoding="utf-8")) == {MONTH: 1}


def _fake_session(monkeypatch):
    response = MagicMock()
    response.json.return_value = {"companyName": "ABC"}
    session = MagicMock()
    session.get.return_value = response
    monkeypatch.setattr(indian_api, "SESSION", session)
    monkeypatch.setattr(indian_api, "BASE_URL", "https://stock.example.invalid")
    monkeypatch.setattr(indian_api, "API_KEY", "secret-key")
    return session


def test_key_goes_only_in_the_header(monkeypatch, tmp_path):
    session = _fake_session(monkeypatch)
    monkeypatch.setattr(indian_api, "INDIAN_API_MONTHLY_LIMIT", 0)
    assert indian_api._request_json("/stock", {"name": "ABC"}, timeout=5) == {"companyName": "ABC"}
    _, kwargs = session.get.call_args
    assert kwargs["params"] == {"name": "ABC"}
    assert "secret-key" not in json.dumps(kwargs["params"])
    assert kwargs["headers"] == {"X-API-Key": "secret-key"}


def test_exhausted_quota_makes_no_request(monkeypatch, tmp_path):
    session = _fake_session(monkeypatch)
    path = tmp_path / "quota.json"
    path.write_text(json.dumps({MONTH: 3}), encoding="utf-8")
    monkeypatch.setattr(indian_api, "INDIAN_API_MONTHLY_LIMIT", 3)
    monkeypatch.setattr(indian_api, "INDIAN_API_QUOTA_FILE", str(path))
    assert indian_api._request_json("/stock", {"name": "ABC"}, timeout=5) is None
    session.get.assert_not_called()


def test_failures_are_not_cached_and_successes_are(monkeypatch):
    indian_api._payload_cache.clear()
    answers = [None, {"companyName": "ABC"}]
    calls = []

    def fake_request(path, params, *, timeout):
        calls.append(params["name"])
        return answers.pop(0) if answers else {"companyName": "stale?"}

    monkeypatch.setattr(indian_api, "_request_json", fake_request)
    assert indian_api._get_stock_payload("ABC", timeout=5) is None
    assert indian_api._get_stock_payload("ABC", timeout=5) == {"companyName": "ABC"}
    assert indian_api._get_stock_payload("ABC", timeout=5) == {"companyName": "ABC"}
    assert calls == ["ABC", "ABC"]  # the failure was retried; the success was cached


def test_cached_payload_expires(monkeypatch):
    indian_api._payload_cache.clear()
    clock = [1000.0]
    monkeypatch.setattr(indian_api.time, "monotonic", lambda: clock[0])
    calls = []
    monkeypatch.setattr(
        indian_api, "_request_json", lambda path, params, *, timeout: calls.append(1) or {"n": len(calls)}
    )
    assert indian_api._get_stock_payload("ABC", timeout=5) == {"n": 1}
    clock[0] += indian_api._PAYLOAD_TTL_SECONDS + 1
    assert indian_api._get_stock_payload("ABC", timeout=5) == {"n": 2}
