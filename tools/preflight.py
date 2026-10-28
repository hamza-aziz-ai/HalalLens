#!/usr/bin/env python3
"""Preflight dependency checks for Halal-Lens services."""

from __future__ import annotations

import logging
import os
import socket
import sys
from typing import Callable, List, Tuple

import psycopg2
import requests
from psycopg2 import OperationalError
from urllib.parse import urlparse

from config import (
    MINIO_ACCESS_KEY,
    MINIO_BUCKET,
    MINIO_HOST,
    MINIO_PORT,
    MINIO_SECRET_KEY,
    NARRATOR_MODE,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
    LLM_ENDPOINT,
    LLM_MODEL,
)
from etl.minio_client import make_storage_client
from config.logging_config import configure_logging


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
configure_logging(
    "preflight",
    level=LOG_LEVEL,
    fmt="%(asctime)s %(levelname)s [preflight] %(message)s",
)
logger = logging.getLogger("preflight")


def _check_postgres() -> bool:
    if not POSTGRES_USER or not POSTGRES_PASSWORD:
        logger.error("PostgreSQL credentials are missing; set POSTGRES_USER/PASSWORD")
        return False
    conn = None
    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            connect_timeout=5,
        )
        logger.info(
            "PostgreSQL reachable at %s:%s/%s", POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
        )
        return True
    except OperationalError as exc:
        logger.error("PostgreSQL connection failed: %s", exc)
        return False
    finally:
        if conn:
            conn.close()


def _check_minio() -> bool:
    if not MINIO_ACCESS_KEY or not MINIO_SECRET_KEY:
        logger.error("MinIO credentials missing; set MINIO_ACCESS_KEY/SECRET_KEY")
        return False
    try:
        client = make_storage_client()
        # Checks the one bucket the app uses: a bucket-scoped token (e.g. an R2
        # "Object Read & Write" token) may not list all buckets.
        if not client.bucket_exists(MINIO_BUCKET):
            logger.error("Object store bucket '%s' not found at %s:%s", MINIO_BUCKET, MINIO_HOST, MINIO_PORT)
            return False
        logger.info("Object store reachable at %s:%s, bucket '%s'", MINIO_HOST, MINIO_PORT, MINIO_BUCKET)
        return True
    except Exception as exc:  # pragma: no cover - network failures
        logger.error("MinIO connection failed: %s", exc)
        return False


def _check_llm_endpoint() -> bool:
    if NARRATOR_MODE.lower() != "llm":
        logger.info("Narrator mode is %s; skipping LLM endpoint check", NARRATOR_MODE)
        return True
    if not LLM_ENDPOINT:
        logger.error("LLM endpoint missing while narrator mode is 'llm'")
        return False
    parsed = urlparse(LLM_ENDPOINT)
    host = parsed.hostname or LLM_ENDPOINT
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=5):
            logger.info("LLM endpoint %s reachable on %s:%s", LLM_ENDPOINT, host, port)
            return True
    except PermissionError as exc:
        logger.warning(
            "LLM endpoint reachability could not be confirmed due to permission error: %s",
            exc,
        )
        return True
    except OSError as exc:
        logger.error("LLM endpoint %s unreachable: %s", LLM_ENDPOINT, exc)
        return False


def _run_checks(checks: List[Tuple[str, Callable[[], bool]]]) -> bool:
    all_ok = True
    logger.info("Running %s dependency checks", len(checks))
    for label, func in checks:
        logger.info("Checking %s …", label)
        if not func():
            all_ok = False
            logger.error("%s check failed", label)
        else:
            logger.info("%s check passed", label)
    return all_ok


def main() -> int:
    checks = [
        ("PostgreSQL", _check_postgres),
        ("MinIO", _check_minio),
        ("LLM/Ollama endpoint", _check_llm_endpoint),
    ]
    passed = _run_checks(checks)
    if not passed:
        logger.critical("Preflight failed — aborting stack start")
        return 1
    logger.info("All dependencies healthy. Safe to launch services.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
