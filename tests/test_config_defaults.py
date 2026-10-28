"""Config defaults must be portable: no developer LAN address, and the Google
sign-in redirect origin follows the deployment's app domain."""

import importlib

import pytest

import config.parameters as parameters

KEYS = ("FRONTEND_BASE_URL", "HALAL_APP_DOMAIN", "POSTGRES_HOST", "MINIO_HOST", "ALLOWED_ORIGINS")


@pytest.fixture
def reload_config(monkeypatch):
    def load(**env):
        for key in KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        return importlib.reload(parameters)

    yield load
    # Leave the module as the rest of the suite expects it.
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    importlib.reload(parameters)


def test_local_defaults(reload_config):
    cfg = reload_config()
    assert cfg.POSTGRES_HOST == "localhost"
    assert cfg.MINIO_HOST == "localhost"
    assert cfg.FRONTEND_BASE_URL == "http://localhost:3000"
    assert cfg.DEFAULT_ALLOWED_ORIGINS == ["http://localhost:3000"]


def test_frontend_follows_the_app_domain(reload_config):
    cfg = reload_config(HALAL_APP_DOMAIN="app.example.com")
    assert cfg.FRONTEND_BASE_URL == "https://app.example.com"
    assert "https://app.example.com" in cfg.DEFAULT_ALLOWED_ORIGINS


def test_explicit_frontend_wins(reload_config):
    cfg = reload_config(HALAL_APP_DOMAIN="app.example.com", FRONTEND_BASE_URL="https://ui.example.org")
    assert cfg.FRONTEND_BASE_URL == "https://ui.example.org"


def test_no_lan_address_in_defaults(reload_config):
    cfg = reload_config()
    values = [cfg.POSTGRES_HOST, cfg.MINIO_HOST, cfg.FRONTEND_BASE_URL, *cfg.DEFAULT_ALLOWED_ORIGINS]
    assert not any("192.168." in value for value in values)
