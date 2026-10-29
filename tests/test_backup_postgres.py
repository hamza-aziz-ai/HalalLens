"""The backup job uploads first and prunes only old copies, never the new one."""

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jobs import backup_postgres

NOW = datetime.datetime(2026, 10, 29, 2, 0, tzinfo=datetime.timezone.utc)


def _obj(name, days_old):
    return SimpleNamespace(object_name=name, last_modified=NOW - datetime.timedelta(days=days_old))


def _client(existing):
    client = MagicMock()
    client.list_objects.return_value = existing
    client.stat_object.return_value = SimpleNamespace(size=123)
    return client


def test_uploads_then_prunes_only_expired_backups():
    old = _obj("backups/postgres/db-old.dump", 20)
    recent = _obj("backups/postgres/db-recent.dump", 3)
    client = _client([old, recent])
    name, pruned = backup_postgres.run_backup(
        client, bucket="b", now=NOW, dump=lambda path: path.write_bytes(b"PGDMP")
    )
    assert name.startswith("backups/postgres/") and name.endswith("-20261029T020000Z.dump")
    client.fput_object.assert_called_once()
    assert pruned == [old.object_name]
    client.remove_object.assert_called_once_with("b", old.object_name)


def test_failed_dump_uploads_and_prunes_nothing():
    client = _client([_obj("backups/postgres/db-old.dump", 20)])

    def broken(path):
        raise RuntimeError("pg_dump: connection refused")

    with pytest.raises(RuntimeError):
        backup_postgres.run_backup(client, bucket="b", now=NOW, dump=broken)
    client.fput_object.assert_not_called()
    client.remove_object.assert_not_called()


def test_empty_dump_is_rejected():
    client = _client([])
    with pytest.raises(RuntimeError, match="empty"):
        backup_postgres.run_backup(client, bucket="b", now=NOW, dump=lambda path: path.write_bytes(b""))
    client.fput_object.assert_not_called()
