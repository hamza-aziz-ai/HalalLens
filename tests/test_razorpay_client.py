"""Razorpay GETs ride out a short rate limit instead of failing the run."""

import pytest

import api.razorpay_client as rz
from api.razorpay_client import RazorpayClient, RazorpayError


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = "rate limited" if status != 200 else ""

    def json(self):
        return self._body


def _client(monkeypatch, responses):
    calls, sleeps = [], []

    def get(url, params=None, auth=None, timeout=None):
        calls.append(url)
        return responses.pop(0)

    monkeypatch.setattr(rz.requests, "get", get)
    monkeypatch.setattr(rz.time, "sleep", sleeps.append)
    return RazorpayClient("k", "s"), calls, sleeps


def test_a_429_is_retried_with_retry_after_then_succeeds(monkeypatch):
    client, calls, sleeps = _client(monkeypatch, [_Resp(429, headers={"Retry-After": "3"}), _Resp(200, {"id": "pay_1"})])
    assert client.fetch_payment("pay_1") == {"id": "pay_1"}
    assert len(calls) == 2 and sleeps == [3.0]


def test_without_retry_after_the_waits_back_off_and_the_last_error_is_raised(monkeypatch):
    client, calls, sleeps = _client(monkeypatch, [_Resp(503), _Resp(429), _Resp(429)])
    with pytest.raises(RazorpayError) as excinfo:
        client.fetch_payment("pay_1")
    assert excinfo.value.status == 429 and len(calls) == 3 and sleeps == [1.0, 2.0]


def test_other_errors_are_not_retried(monkeypatch):
    client, calls, sleeps = _client(monkeypatch, [_Resp(401)])
    with pytest.raises(RazorpayError) as excinfo:
        client.fetch_payment("pay_1")
    assert excinfo.value.auth_failure and len(calls) == 1 and sleeps == []


def test_a_large_retry_after_is_capped(monkeypatch):
    client, _, sleeps = _client(monkeypatch, [_Resp(429, headers={"Retry-After": "120"}), _Resp(200, {})])
    client.fetch_payment("pay_1")
    assert sleeps == [rz.MAX_RETRY_DELAY]
