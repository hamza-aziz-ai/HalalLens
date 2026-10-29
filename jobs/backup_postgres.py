#!/usr/bin/env python3
"""Back up PostgreSQL to the object store and prune old copies.

Each run writes ``pg_dump --format=custom`` of the app database to
``<BACKUP_PREFIX><db>-<UTC timestamp>.dump`` in ``MINIO_BUCKET`` (Cloudflare R2
in production), then deletes backups under the prefix older than
``BACKUP_RETENTION_DAYS``. Pruning runs only after a successful upload, so a
failing dump never removes the last good copy.

    python -m jobs.backup_postgres          # one backup, then exit
    python -m jobs.backup_postgres --loop   # every BACKUP_INTERVAL_HOURS

Restore: download a ``.dump`` and run
``pg_restore --clean --if-exists --no-owner -d <db> <file>`` (README_ops).
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import subprocess
import tempfile
import time
import traceback
from pathlib import Path

from config import (
    MINIO_BUCKET,
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from config.logging_config import configure_logging
from etl.minio_client import make_storage_client
from monitoring.notifier import OpsNotifier

logger = logging.getLogger("backup")

PREFIX = os.getenv("BACKUP_PREFIX", "backups/postgres/")
RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "14"))
INTERVAL_HOURS = float(os.getenv("BACKUP_INTERVAL_HOURS", "24"))
RETRY_MINUTES = 60


def dump_database(path: Path) -> None:
    """Write a custom-format dump of the app database to ``path``."""

    subprocess.run(
        [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--host", POSTGRES_HOST,
            "--port", str(POSTGRES_PORT),
            "--username", POSTGRES_USER or "",
            "--dbname", POSTGRES_DB,
            "--file", str(path),
        ],
        check=True,
        env={**os.environ, "PGPASSWORD": POSTGRES_PASSWORD or ""},
        capture_output=True,
        text=True,
    )


def run_backup(client, *, bucket: str = MINIO_BUCKET, now: datetime.datetime | None = None,
               dump=dump_database) -> tuple[str, list[str]]:
    """Dump, upload and prune; return the new object name and the pruned ones."""

    now = now or datetime.datetime.now(datetime.timezone.utc)
    name = f"{PREFIX}{POSTGRES_DB}-{now:%Y%m%dT%H%M%SZ}.dump"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "db.dump"
        dump(path)
        if path.stat().st_size == 0:
            raise RuntimeError("pg_dump produced an empty file")
        client.fput_object(bucket, name, str(path), content_type="application/octet-stream")
    logger.info("Uploaded backup %s (%d bytes)", name, client.stat_object(bucket, name).size)

    cutoff = now - datetime.timedelta(days=RETENTION_DAYS)
    pruned = []
    for obj in client.list_objects(bucket, prefix=PREFIX, recursive=True):
        if obj.object_name != name and obj.last_modified and obj.last_modified < cutoff:
            client.remove_object(bucket, obj.object_name)
            pruned.append(obj.object_name)
    if pruned:
        logger.info("Pruned %d backups older than %d days", len(pruned), RETENTION_DAYS)
    return name, pruned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--loop", action="store_true", help="repeat every BACKUP_INTERVAL_HOURS")
    args = parser.parse_args()
    configure_logging("backup", level=os.getenv("LOG_LEVEL", "INFO").upper(),
                      fmt="%(asctime)s %(levelname)s [backup] %(message)s")
    notifier = OpsNotifier(component="backup")
    while True:
        try:
            run_backup(make_storage_client())
            delay = INTERVAL_HOURS * 3600
        except Exception as exc:
            details = getattr(exc, "stderr", None) or traceback.format_exc()
            logger.error("Backup failed: %s", details)
            notifier.notify("ERROR", "PostgreSQL backup failed", details=details)
            if not args.loop:
                raise SystemExit(1)
            delay = RETRY_MINUTES * 60
        if not args.loop:
            return
        time.sleep(delay)


if __name__ == "__main__":
    main()
