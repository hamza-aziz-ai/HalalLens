"""LLM client: Ollama's native /api/chat, the per-process call cap and the
circuit breaker that protect a free cloud allowance (no network)."""

from unittest.mock import MagicMock

import pytest
import requests

import narrator.llm as llm
from narrator.llm import LLMClient, LLMNarrationError


@pytest.fixture(autouse=True)
def fresh_guard(monkeypatch):
    monkeypatch.setattr(llm, "_GUARD", llm._CallGuard())


def _client(json_body=None, exc=None):
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = json_body
    if exc:
        session.post.side_effect = exc
    else:
        session.post.return_value = response
    client = LLMClient(endpoint="http://ollama:11434/api/chat", model="gpt-oss:120b-cloud",
                       provider="ollama", timeout=5, session=session)
    return client, session


def test_ollama_native_request_and_answer():
    client, session = _client({"message": {"role": "assistant", "content": '{"ok": 1}',
                                            "thinking": "reasoning is ignored"}})
    assert client.complete([{"role": "user", "content": "hi"}], temperature=0.0, max_tokens=400) == '{"ok": 1}'
    payload = session.post.call_args.kwargs["json"]
    assert payload["stream"] is False and payload["think"] == "low"
    # num_predict must cover reasoning plus answer.
    assert payload["options"]["num_predict"] == 1024 and payload["options"]["temperature"] == 0.0
    assert "Authorization" not in (session.post.call_args.kwargs.get("headers") or {})


@pytest.mark.parametrize("body", [{}, {"message": {"content": ""}}, {"message": {"content": "  "}},
                                  {"message": {"content": "x" * (64 * 1024 + 1)}}, ["not", "a", "dict"]])
def test_ollama_bad_answers_are_failures(body):
    client, _ = _client(body)
    with pytest.raises(LLMNarrationError):
        client.complete([{"role": "user", "content": "hi"}])


def test_call_cap_refuses_without_calling_the_model():
    client, session = _client({"message": {"content": "ok"}})
    for _ in range(6):
        client.complete([{"role": "user", "content": "hi"}])
    with pytest.raises(LLMNarrationError, match="budget"):
        client.complete([{"role": "user", "content": "hi"}])
    assert session.post.call_count == 6


def test_breaker_opens_after_three_failures_in_a_row():
    client, session = _client(exc=requests.ConnectionError("down"))
    for _ in range(3):
        with pytest.raises(LLMNarrationError, match="request failed"):
            client.complete([{"role": "user", "content": "hi"}])
    with pytest.raises(LLMNarrationError, match="circuit open"):
        client.complete([{"role": "user", "content": "hi"}])
    assert session.post.call_count == 3


def test_breaker_closes_after_the_cooldown(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    client, session = _client(exc=requests.ConnectionError("down"))
    for _ in range(3):
        with pytest.raises(LLMNarrationError):
            client.complete([{"role": "user", "content": "hi"}])
    clock[0] += 61
    session.post.side_effect = None
    session.post.return_value.json.return_value = {"message": {"content": "back"}}
    assert client.complete([{"role": "user", "content": "hi"}]) == "back"
