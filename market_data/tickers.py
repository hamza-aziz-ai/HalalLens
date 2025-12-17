#!/usr/bin/env python3
"""Helpers for constructing ticker candidates."""

from __future__ import annotations

from typing import List, Optional


def build_ticker_candidates(
    primary: str,
    alias: Optional[str] = None,
    additional: Optional[List[str]] = None,
    default_exchange: str = "BO",
) -> List[str]:
    candidates: List[str] = []

    def format_value(value: Optional[str]) -> str:
        if not value:
            return ""
        token = value.strip().upper().replace(" ", "")
        if not token:
            return ""
        if token.endswith((".NS", ".BO")):
            return token
        if token.isdigit():
            return f"{token}.{default_exchange}"
        return f"{token}.{default_exchange}"

    def add(value: Optional[str]) -> None:
        formatted = format_value(value)
        if formatted and formatted not in candidates:
            candidates.append(formatted)

    add(primary)
    if alias:
        alias_clean = alias.replace(" ", "")
        add(alias_clean)
    if additional:
        for extra in additional:
            extra_formatted = format_value(extra)
            if extra_formatted and extra_formatted not in candidates:
                candidates.append(extra_formatted)

    return candidates


def build_tiingo_tickers(
    primary: str,
    alias: Optional[str] = None,
    additional: Optional[List[str]] = None,
) -> List[str]:
    """Return Tiingo-compatible ticker strings (BOM:CODE)."""

    values: List[str] = []

    def normalize(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        token = value.strip().upper()
        if not token:
            return None
        for suffix in (".BO", ".NS"):
            if token.endswith(suffix):
                token = token[: -len(suffix)]
        return token or None

    seen = set()
    for candidate in [primary, alias, *(additional or [])]:
        norm = normalize(candidate)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        values.append(f"BOM:{norm}")

    return values


__all__ = ["build_ticker_candidates", "build_tiingo_tickers"]
