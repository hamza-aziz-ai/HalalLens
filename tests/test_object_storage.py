"""The PDF store must work with any S3-compatible service (MinIO, Cloudflare R2)
from configuration alone: HTTPS, region and bucket come from config."""

from unittest.mock import MagicMock

import pytest

import etl.minio_client as storage


@pytest.fixture
def fake_minio(monkeypatch):
    created = []

    def factory(**kwargs):
        client = MagicMock(name="Minio")
        client.bucket_exists.return_value = True
        created.append((kwargs, client))
        return client

    monkeypatch.setattr(storage, "Minio", factory)
    return created


def _configure(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setattr(storage, name, value)


def test_r2_style_config_reaches_the_client(monkeypatch, fake_minio):
    _configure(
        monkeypatch,
        MINIO_HOST="acct.r2.cloudflarestorage.com",
        MINIO_PORT=443,
        MINIO_ACCESS_KEY="key",
        MINIO_SECRET_KEY="secret",
        MINIO_SECURE=True,
        MINIO_REGION="auto",
        MINIO_BUCKET="halallens-pdfs",
    )
    pdfs = storage.BSEPDFStorage()
    kwargs, client = fake_minio[0]
    assert kwargs == {
        "endpoint": "acct.r2.cloudflarestorage.com:443",
        "access_key": "key",
        "secret_key": "secret",
        "secure": True,
        "region": "auto",
    }
    assert pdfs.bucket_name == "halallens-pdfs"
    client.bucket_exists.assert_called_once_with("halallens-pdfs")
    client.make_bucket.assert_not_called()


def test_local_minio_defaults(monkeypatch, fake_minio):
    _configure(monkeypatch, MINIO_HOST="localhost", MINIO_PORT=9000,
               MINIO_SECURE=False, MINIO_REGION=None, MINIO_BUCKET="bse-pdfs")
    storage.make_storage_client()
    kwargs, _ = fake_minio[0]
    assert kwargs["endpoint"] == "localhost:9000"
    assert kwargs["secure"] is False and kwargs["region"] is None


def test_missing_bucket_is_created(monkeypatch, fake_minio):
    _configure(monkeypatch, MINIO_BUCKET="bse-pdfs")

    def factory(**kwargs):
        client = MagicMock(name="Minio")
        client.bucket_exists.return_value = False
        fake_minio.append((kwargs, client))
        return client

    monkeypatch.setattr(storage, "Minio", factory)
    storage.BSEPDFStorage()
    fake_minio[-1][1].make_bucket.assert_called_once_with("bse-pdfs")
