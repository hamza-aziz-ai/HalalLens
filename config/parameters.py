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


POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = _as_int(os.getenv("POSTGRES_PORT"), 5432)
POSTGRES_DB = os.getenv("POSTGRES_DB", "Halal-Lens")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")

MINIO_HOST = os.getenv("MINIO_HOST", "host.docker.internal")
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
INDIAN_API_BASE_URL = os.getenv("INDIAN_API_BASE_URL")
INDIAN_API_KEY = os.getenv("INDIAN_API_KEY")
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

DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
ALLOWED_ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX", r"http://(127\.0\.0\.1|localhost):\d+"
)
