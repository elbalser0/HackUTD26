from __future__ import annotations

import pytest

from breakglass import storage
from breakglass.config import ConfigError, load_settings
from breakglass.db import Database

SECRET = "s3cr3t-pw"
GOOD = f"postgresql://tsdbadmin:{SECRET}@abc123.tsdb.cloud.timescale.com:35432/tsdb?sslmode=require"


def test_unset_url_means_sqlite(monkeypatch, tmp_path):
    monkeypatch.delenv("BG_DATABASE_URL", raising=False)
    monkeypatch.setenv("BG_DB_PATH", str(tmp_path / "x.db"))
    s = load_settings()
    assert s.database_url is None
    d = storage.open_database(s)
    try:
        assert isinstance(d, Database)
    finally:
        d.close()


def test_blank_url_means_sqlite(monkeypatch):
    monkeypatch.setenv("BG_DATABASE_URL", "   ")
    assert load_settings().database_url is None


def test_url_is_secret_not_in_repr(monkeypatch):
    monkeypatch.setenv("BG_DATABASE_URL", GOOD)
    s = load_settings()
    assert s.database_url == GOOD
    assert SECRET not in repr(s)


@pytest.mark.parametrize("bad", ["mysql://u:p@h/db", "sqlite:///x.db", "not a url", "postgresql://", "postgresql:///db"])
def test_bad_urls_fail_with_redacted_error(monkeypatch, bad):
    monkeypatch.setenv("BG_DATABASE_URL", bad)
    with pytest.raises(ConfigError) as ei:
        load_settings()
    assert "(value hidden)" in str(ei.value)


def test_secret_never_leaks_in_error(monkeypatch):
    monkeypatch.setenv("BG_DATABASE_URL", f"mysql://u:{SECRET}@h/db")
    with pytest.raises(ConfigError) as ei:
        load_settings()
    assert SECRET not in str(ei.value)


def test_configured_postgres_failure_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("BG_DB_PATH", str(tmp_path / "fallback.db"))
    monkeypatch.setenv("BG_DATABASE_URL", f"postgresql://u:{SECRET}@127.0.0.1:1/db?connect_timeout=1")
    s = load_settings()
    with pytest.raises(storage.StorageUnavailable) as ei:
        storage.open_database(s)
    assert SECRET not in str(ei.value) and SECRET not in repr(ei.value)
    assert not (tmp_path / "fallback.db").exists()  # SQLite was not silently created
