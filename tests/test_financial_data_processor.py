#!/usr/bin/env python3
"""Unit tests for FinancialDataProcessor helpers."""

import pytest

from etl.financial_data_processor import FinancialDataProcessor as FDP


def test_extract_governance_notes_captures_sentence():
    text = (
        "The board confirms its Shariah governance framework. "
        "Non-permissible income will be donated to charity as part of cleansing."
    )
    note = FDP._extract_governance_notes(text)
    assert note is not None
    assert "Non-permissible income" in note


def test_extract_non_halal_from_text_handles_units():
    text = "Non-permissible income for FY24 stood at INR 3.2 crore which will be donated."
    value = FDP._extract_non_halal_from_text(text)
    assert value == pytest.approx(3.2 * 10_000_000)


def test_extract_non_halal_from_text_without_unit_uses_scale():
    text = "Impermissible income amounted to 450000 which will be donated."
    value = FDP._extract_non_halal_from_text(text)
    assert value == pytest.approx(450000)


def test_parse_xbrl_extracts_metrics():
    xml = b"""
    <xbrl>
      <RevenueFromOperations>100</RevenueFromOperations>
      <TradeReceivablesCurrent>50</TradeReceivablesCurrent>
      <CashAndCashEquivalents>25</CashAndCashEquivalents>
    </xbrl>
    """
    metrics = FDP._parse_xbrl(xml, scale_hint=1.0)
    assert metrics["revenue"] == 100
    assert metrics["accounts_receivable"] == 50
    assert metrics["cash_equiv"] == 25


def test_parse_structured_json_handles_nested_keys():
    payload = {
        "Financials": {
            "Borrowings": {"Total": "200"},
            "NonPermissible": {"Income": 5.5},
        }
    }
    metrics = FDP._parse_structured_json(payload, scale_hint=1.0)
    assert metrics["total_debt"] == 200
    assert metrics["non_halal_income"] == 5.5
