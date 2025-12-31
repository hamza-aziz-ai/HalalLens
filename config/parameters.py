#!/usr/bin/env python3
"""
Project configurations
"""

import json
import os
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

load_dotenv()


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _as_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lower() for item in value.split(",") if item.strip()]


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "192.168.1.9")
POSTGRES_PORT = _as_int(os.getenv("POSTGRES_PORT"), 5432)
POSTGRES_DB = os.getenv("POSTGRES_DB", "Halal-Lens")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

MINIO_HOST = os.getenv("MINIO_HOST", "192.168.1.9")
MINIO_PORT = _as_int(os.getenv("MINIO_PORT"), 9000)
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

NARRATOR_MODE = os.getenv("NARRATOR_MODE", "rule_based")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "vllm")
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT")
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_TEMPERATURE = _as_float(os.getenv("LLM_TEMPERATURE"), 0.0)
LLM_MAX_TOKENS = _as_int(os.getenv("LLM_MAX_TOKENS"), 400)
LLM_TIMEOUT = _as_float(os.getenv("LLM_TIMEOUT"), 30.0)
NARRATION_TIMEOUT_SECONDS = _as_float(
    os.getenv("NARRATION_TIMEOUT_SECONDS"), 8.0
)
NARRATION_QUEUE_TIMEOUT_SECONDS = _as_float(
    os.getenv("NARRATION_QUEUE_TIMEOUT_SECONDS"), 0.5
)
NARRATION_MAX_WORKERS = _as_int(os.getenv("NARRATION_MAX_WORKERS"), 4)
NARRATION_MAX_CONCURRENT = _as_int(os.getenv("NARRATION_MAX_CONCURRENT"), 4)
NARRATION_CACHE_TTL_SECONDS = _as_int(
    os.getenv("NARRATION_CACHE_TTL_SECONDS"), 300
)
HISTORY_CACHE_TTL_SECONDS = _as_int(os.getenv("HISTORY_CACHE_TTL_SECONDS"), 60)
RECENT_CACHE_TTL_SECONDS = _as_int(os.getenv("RECENT_CACHE_TTL_SECONDS"), 30)
INDIAN_API_BASE_URL = os.getenv("INDIAN_API_BASE_URL")
INDIAN_API_KEY = os.getenv("INDIAN_API_KEY")
INDIAN_API_OVERRIDE_TOLERANCE = _as_float(
    os.getenv("INDIAN_API_OVERRIDE_TOLERANCE"), 0.15
)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")
OAUTH_STATE_SECRET = os.getenv("OAUTH_STATE_SECRET")
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://192.168.1.9:3001")
HALAL_APP_DOMAIN = os.getenv("HALAL_APP_DOMAIN", "").strip()
ADMIN_EMAILS = _as_list(os.getenv("ADMIN_EMAILS"))
TICKER_MAP_PATH = Path(__file__).resolve().parent / "ticker_map.json"
TICKER_MAP: Dict[str, str] = {}
if TICKER_MAP_PATH.exists():
    with TICKER_MAP_PATH.open("r", encoding="utf-8") as handle:
        TICKER_MAP.update(json.load(handle))

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = _as_int(os.getenv("SMTP_PORT"), 587)
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
ALERT_EMAIL_SENDER = os.getenv("ALERT_EMAIL_SENDER")
ALERT_EMAIL_RECIPIENT = os.getenv("ALERT_EMAIL_RECIPIENT")
AUTH_TOKEN_TTL_HOURS = _as_int(os.getenv("AUTH_TOKEN_TTL_HOURS"), 24 * 30)
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET")
SUBSCRIPTION_PLAN_CODE = os.getenv("SUBSCRIPTION_PLAN_CODE", "starter")
SUBSCRIPTION_PRICE_INR = _as_int(os.getenv("SUBSCRIPTION_PRICE_INR"), 50)
SUBSCRIPTION_INTERVAL_DAYS = _as_int(os.getenv("SUBSCRIPTION_INTERVAL_DAYS"), 30)

DEFAULT_ALLOWED_ORIGINS = [
    "http://192.168.1.9:3000",
    "http://192.168.1.9:3001",
]
if HALAL_APP_DOMAIN:
    DEFAULT_ALLOWED_ORIGINS.extend(
        [
            f"https://{HALAL_APP_DOMAIN}",
            f"https://www.{HALAL_APP_DOMAIN}",
        ]
    )
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
ALLOWED_ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX", r"http://192\.168\.1\.9:\d+"
)
