#!/usr/bin/env python3
"""Dataclasses shared by narrator implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class NarrationResult:
    """Container for narrator output."""

    summary: str
    verdict: str
    bullets: List[str]
    citations: List[str]
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class NarratorConfig:
    """Configuration for selecting narrator behavior."""

    mode: str = "rule_based"  # or "llm"
    provider: str = "vllm"
    endpoint: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 400
    timeout: float = 30.0

    @classmethod
    def default(cls) -> "NarratorConfig":
        return cls()
