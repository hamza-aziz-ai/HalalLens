"""Centralized logging configuration for HalalLens services."""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import re
from logging.handlers import TimedRotatingFileHandler


def configure_logging(
    component: str,
    *,
    level: Optional[str] = None,
    fmt: Optional[str] = None,
    datefmt: Optional[str] = None,
) -> Path:
    """Configure logging for a given component with day-scoped log files.

    Logs are written to <LOG_ROOT>/<component>/<YYYY>/<MM>/<DD>/<component>.log
    and also mirrored to stdout so Docker/K8s still captures them.
    """

    log_level_name = (level or os.getenv("LOG_LEVEL", "DEBUG")).upper()
    log_level = getattr(logging, log_level_name, logging.DEBUG)
    log_format = fmt or os.getenv(
        "LOG_FORMAT", "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    date_format = datefmt or os.getenv(
        "LOG_DATE_FORMAT", "%A %d-%m-%Y %I:%M:%S %p"
    )

    log_root = Path(os.getenv("HALAL_LOG_ROOT", "logs"))
    now = datetime.now()
    log_dir = log_root / component / now.strftime("%Y") / now.strftime("%B")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{component}.log"
    try:
        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", "31")),
            encoding="utf-8",
            utc=False,
        )
    except PermissionError:
        fallback_root = Path(os.getenv("HALAL_LOG_FALLBACK_ROOT", "logs_runtime"))
        fallback_dir = fallback_root / component / now.strftime("%Y") / now.strftime("%B")
        fallback_dir.mkdir(parents=True, exist_ok=True)
        log_file = fallback_dir / f"{component}.log"
        file_handler = TimedRotatingFileHandler(
            filename=log_file,
            when="midnight",
            interval=1,
            backupCount=int(os.getenv("LOG_BACKUP_COUNT", "31")),
            encoding="utf-8",
            utc=False,
        )
        logging.getLogger(component).warning(
            "Log directory permission denied, using fallback %s", log_file
        )
    file_handler.suffix = "%d-%m-%Y"
    file_handler.extMatch = re.compile(r"^\d{2}-\d{2}-\d{4}$")

    stream_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(log_format, datefmt=date_format)
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(stream_handler)

    logging.getLogger(component).info("Logging to %s", log_file)
    return log_file


__all__ = ["configure_logging"]
