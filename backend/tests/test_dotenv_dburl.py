"""BG_DATABASE_URL comes from the repo-root .env like every other BG_* setting.
The real environment still wins, the value stays out of repr and errors, and
os.environ is never modified."""

from __future__ import annotations

import os

import pytest

from breakglass import config

DB_SECRET = "dotenv-db-pw"
DB_URL = f"postgresql://tsdbadmin:{DB_SECRET}@abc123.tsdb.cloud.timescale.com:35432/tsdb?sslmode=require"
NL = "\n"


@pytest.fixture
def dotenv(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setenv("BG_DOTENV_FILE", str(p))
    monkeypatch.delenv("BG_NO_DOTENV", raising=False)
    monkeypatch.delenv("BG_DATABASE_URL", raising=False)
    return p


def test_database_url_from_dotenv_is_used(dotenv):
    dotenv.write_text(f"BG_DATABASE_URL={DB_URL}{NL}", encoding="utf-8")
    s = config.load_settings()
    assert s.database_url == DB_URL
    assert DB_SECRET not in repr(s)
    assert "BG_DATABASE_URL" not in os.environ


def test_shell_database_url_wins_over_dotenv(dotenv, monkeypatch):
    dotenv.write_text(f"BG_DATABASE_URL=postgresql://u:p@file-host:5432/db{NL}", encoding="utf-8")
    monkeypatch.setenv("BG_DATABASE_URL", DB_URL)
    assert config.load_settings().database_url == DB_URL


def test_bad_database_url_from_dotenv_is_redacted(dotenv):
    dotenv.write_text(f"BG_DATABASE_URL=mysql://u:{DB_SECRET}@h/db{NL}", encoding="utf-8")
    with pytest.raises(config.ConfigError) as ei:
        config.load_settings()
    assert DB_SECRET not in str(ei.value)


def test_database_url_opt_out_ignores_dotenv(dotenv, monkeypatch):
    dotenv.write_text(f"BG_DATABASE_URL={DB_URL}{NL}", encoding="utf-8")
    monkeypatch.setenv("BG_NO_DOTENV", "1")
    assert config.load_settings().database_url is None
