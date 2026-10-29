#!/usr/bin/env python3
"""Sanity checks for Indian API helpers."""

from market_data import indian_api


def test_currency_metrics_scaled_to_rupees():
    flat = {
        "totaldebt": 10.0,
        "cashequivalents": 5.0,
        "totalreceivablesnet": 2.0,
        "totalrevenue": 50.0,
        "interestincome": 1.0,
        "totalcashdividendspaid": 0.5,
        "othernet": 0.25,
    }

    metrics = indian_api._build_metrics(flat)  # pylint: disable=protected-access

    assert metrics["total_debt"] == 10.0 * indian_api.INR_CRORE
    assert metrics["cash_equiv"] == 5.0 * indian_api.INR_CRORE
    assert metrics["accounts_receivable"] == 2.0 * indian_api.INR_CRORE
    assert metrics["revenue"] == 50.0 * indian_api.INR_CRORE
    assert metrics["interest_income"] == 1.0 * indian_api.INR_CRORE
    assert "dividend_income" not in metrics
    # D-028: "Other, Net" is not prohibited income.
    assert "non_halal_income" not in metrics


def test_market_cap_scaled_from_crore():
    payload = {"marketCap": "123.45"}
    cap = indian_api._extract_market_cap(  # pylint: disable=protected-access
        payload,
        share_price=None,
        shares_outstanding=None,
    )
    assert cap == 123.45 * indian_api.INR_CRORE
