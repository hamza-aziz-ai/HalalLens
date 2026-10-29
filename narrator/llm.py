#!/usr/bin/env python3
"""LLM-backed narration support."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Sequence

import requests
from requests import HTTPError, RequestException

from narrator.models import NarrationResult, NarratorConfig
from ratio_engine import RatioEvaluation


class LLMNarrationError(RuntimeError):
    """Raised when the LLM narrator cannot produce a valid response."""


class _CallGuard:
    """Process-wide cap and circuit breaker for model calls.

    Protects a free cloud allowance and the API's narration workers: at most
    ``max_calls`` per ``window_s`` across the process, and after
    ``break_after`` failures in a row the model is skipped for ``cooldown_s``
    (then one call is let through to probe). Every refusal raises
    LLMNarrationError, so callers fall back to the rule-based text.
    ponytail: per-process (one API worker); share via Redis with more workers.
    """

    def __init__(self, max_calls: int = 6, window_s: float = 60.0,
                 break_after: int = 3, cooldown_s: float = 60.0) -> None:
        self.max_calls, self.window_s = max_calls, window_s
        self.break_after, self.cooldown_s = break_after, cooldown_s
        self._lock = threading.Lock()
        self._calls: Deque[float] = deque()
        self._failures = 0
        self._open_until = 0.0

    def before_call(self) -> None:
        now = time.monotonic()
        with self._lock:
            if now < self._open_until:
                raise LLMNarrationError("LLM circuit open after repeated failures")
            while self._calls and now - self._calls[0] > self.window_s:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                raise LLMNarrationError("LLM call budget exhausted for this minute")
            self._calls.append(now)

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self._failures = 0
                return
            self._failures += 1
            if self._failures >= self.break_after:
                self._open_until = time.monotonic() + self.cooldown_s
                self._failures = 0


_GUARD = _CallGuard()


@dataclass
class LLMClient:
    """Small helper to call OpenAI-compatible chat endpoints."""

    endpoint: str
    model: str
    api_key: str | None = None
    provider: str = "vllm"
    timeout: float | None = 30.0
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()

    @classmethod
    def from_config(cls, config: NarratorConfig) -> "LLMClient":
        if not config.endpoint or not config.model:
            raise LLMNarrationError("LLM endpoint and model must be configured")
        return cls(
            endpoint=config.endpoint,
            model=config.model,
            api_key=config.api_key,
            provider=config.provider,
            timeout=config.timeout,
        )

    def complete(
        self,
        messages: Sequence[dict],
        temperature: float = 0.0,
        max_tokens: int = 400,
    ) -> str:
        _GUARD.before_call()
        try:
            if self.provider == "ollama":
                content = self._complete_ollama(messages, temperature, max_tokens)
            else:
                content = self._complete_openai(messages, temperature, max_tokens)
        except LLMNarrationError:
            _GUARD.record(ok=False)
            raise
        _GUARD.record(ok=True)
        return content

    def _complete_ollama(
        self, messages: Sequence[dict], temperature: float, max_tokens: int
    ) -> str:
        """Ollama's native /api/chat (LLM_ENDPOINT=http://<host>:11434/api/chat).

        Used for cloud models such as gpt-oss:120b-cloud through a signed-in
        daemon. Reasoning comes back separately in message.thinking and is
        ignored; num_predict must cover reasoning plus answer, so it is never
        below 1024. Output schemas are not relied on: the caller validates.
        """

        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "think": "low",
            "options": {
                "temperature": temperature,
                "seed": 7,
                "num_predict": max(max_tokens or 0, 1024),
            },
        }
        timeout = self.timeout if self.timeout and self.timeout > 0 else None
        try:
            response = self.session.post(self.endpoint, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except (RequestException, HTTPError, ValueError) as exc:
            raise LLMNarrationError(f"LLM request failed: {exc}") from exc
        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMNarrationError("LLM response missing content")
        if len(content) > 64 * 1024:
            raise LLMNarrationError("LLM response too large")
        return content

    def _complete_openai(
        self, messages: Sequence[dict], temperature: float, max_tokens: int
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens and max_tokens > 0:
            payload["max_tokens"] = max_tokens

        timeout = self.timeout if self.timeout and self.timeout > 0 else None
        try:
            response = self.session.post(
                self.endpoint, headers=headers, json=payload, timeout=timeout
            )
            response.raise_for_status()
        except (RequestException, HTTPError) as exc:
            raise LLMNarrationError(f"LLM request failed: {exc}") from exc
        data = response.json()
        choices = data.get("choices")
        if not choices:
            raise LLMNarrationError("LLM response missing choices")
        choice = choices[0]
        content = self._extract_content(choice)
        if not content:
            raise LLMNarrationError(
                f"LLM response missing content: {json.dumps(choice)}"
            )
        return content

    def _extract_content(self, choice: dict) -> str:
        message = choice.get("message")
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            raw = message.get("content")
            if isinstance(raw, str):
                return raw
            if isinstance(raw, list):
                return "".join(
                    part if isinstance(part, str) else part.get("text", "")
                    for part in raw
                )

        text = choice.get("text")
        if isinstance(text, str):
            return text

        raw_content = choice.get("content")
        if isinstance(raw_content, str):
            return raw_content

        delta = choice.get("delta")
        if isinstance(delta, dict):
            delta_content = delta.get("content")
            if isinstance(delta_content, str):
                return delta_content
            if isinstance(delta_content, list):
                return "".join(
                    part if isinstance(part, str) else part.get("text", "")
                    for part in delta_content
                )

        return ""


class LLMNarrationEngine:
    """Build narrations via LLM prompts."""

    SYSTEM_PROMPT = (
        "You are an Islamic finance compliance analyst. "
        "Given ratio facts and the screening verdict you must explain the result; "
        "never contradict the verdict. "
        "Respond strictly as JSON with keys summary, verdict, bullets, citations, screen_verdict."
    )

    def __init__(self, client: LLMClient, config: NarratorConfig):
        self.client = client
        self.config = config

    def build(self, evaluation: RatioEvaluation) -> NarrationResult:
        facts = self._format_facts(evaluation)
        prompt = self._build_prompt(evaluation, facts)
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        raw = self.client.complete(
            messages,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        return self._parse_response(raw)

    def _format_facts(self, evaluation: RatioEvaluation) -> List[str]:
        facts: List[str] = []
        for key, computation in evaluation.ratios.items():
            label = key.replace("_", " ").title()
            if computation.value is None:
                facts.append(f"{label}: unavailable ({computation.note})")
                continue
            value_pct = computation.value * 100
            threshold_pct = computation.threshold * 100
            verdict = "PASS" if computation.passed else "FAIL"
            facts.append(
                f"{label}: {value_pct:.2f}% vs {threshold_pct:.0f}% cap -> {verdict}"
            )
        if not facts:
            facts.append("No ratios computed due to missing data.")
        return facts

    def _build_prompt(self, evaluation: RatioEvaluation, facts: List[str]) -> str:
        citation = f"Filing date: {evaluation.filing_date.date().isoformat()}"
        return (
            f"Symbol: {evaluation.symbol}\n"
            f"{citation}\n"
            f"Screening verdict (authoritative): {evaluation.verdict}\n"
            "Facts:\n- " + "\n- ".join(facts) + "\n"
            "Return JSON with keys summary, verdict, bullets, citations, screen_verdict "
            "where screen_verdict repeats the authoritative verdict above exactly, "
            "bullets reference the numeric facts and citations mention the filing date."
        )

    def _parse_response(self, raw: str) -> NarrationResult:
        cleaned = self._strip_code_fence(raw.strip())
        if not cleaned:
            raise LLMNarrationError("LLM response was empty")
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            fragment = self._extract_json_fragment(cleaned)
            if fragment:
                try:
                    parsed = json.loads(fragment)
                except json.JSONDecodeError as inner_exc:
                    raise LLMNarrationError("LLM response was not valid JSON") from inner_exc
            else:
                raise LLMNarrationError("LLM response was not valid JSON") from exc

        summary = parsed.get("summary")
        verdict = parsed.get("verdict")
        bullets = parsed.get("bullets") or []
        citations = parsed.get("citations") or []
        if not summary or not verdict or not isinstance(bullets, list):
            raise LLMNarrationError("LLM response missing required fields")
        if not citations:
            citations = ["Source: latest filing"]

        return NarrationResult(
            summary=summary,
            verdict=verdict,
            bullets=[str(b) for b in bullets],
            citations=[str(c) for c in citations],
            # What the model says the verdict is; NarrationEngine compares it to the
            # engine's before accepting the text.
            metadata={"source": "llm", "claimed_verdict": str(parsed.get("screen_verdict") or "")},
        )

    @staticmethod
    @staticmethod
    def _strip_code_fence(raw: str) -> str:
        if raw.startswith("```"):
            fence_end = raw.rfind("```")
            if fence_end > 0:
                header_end = raw.find("\n")
                body_start = header_end + 1 if header_end != -1 else 3
                return raw[body_start:fence_end].strip()
        return raw

    @staticmethod
    def _extract_json_fragment(raw: str) -> str | None:
        """Try to salvage JSON embedded inside fences or prose."""
        start = None
        depth = 0
        in_string = False
        escape = False
        for idx, ch in enumerate(raw):
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = idx
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start is not None:
                        return raw[start : idx + 1]
        return None
        return raw[start : end + 1]


__all__ = ["LLMNarrationEngine", "LLMNarrationError", "LLMClient"]
