"""Backend settings from the repo-root .env: only BG_* keys, real env wins,
nothing else (e.g. DIGITALOCEAN_TOKEN) is read, and os.environ is untouched."""

from __future__ import annotations

import os

import pytest

from breakglass import config

FAKE_TOKEN = "dop_v1_fake_not_a_real_token"


@pytest.fixture
def dotenv(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    monkeypatch.setenv("BG_DOTENV_FILE", str(p))
    monkeypatch.delenv("BG_NO_DOTENV", raising=False)
    for k in ("BG_FIREBASE_PROJECT_ID", "BG_ADMIN_EMAILS", "BG_ADMIN_TOKEN", "BG_ENVIRONMENT",
              "DIGITALOCEAN_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    return p


def test_bg_keys_from_dotenv_are_used(dotenv):
    dotenv.write_text("BG_FIREBASE_PROJECT_ID=argus-demo\nBG_ADMIN_EMAILS=A@x.com, b@y.com\n", encoding="utf-8")
    s = config.load_settings()
    assert s.firebase_project_id == "argus-demo"
    assert s.admin_emails == ("a@x.com", "b@y.com")


def test_non_bg_keys_are_never_read_or_exported(dotenv):
    dotenv.write_text(f"DIGITALOCEAN_TOKEN={FAKE_TOKEN}\nBG_ENVIRONMENT=demo2\n", encoding="utf-8")
    keys = config.read_dotenv_bg(dotenv)
    assert keys == {"BG_ENVIRONMENT": "demo2"}
    s = config.load_settings()
    assert s.environment == "demo2"
    assert "DIGITALOCEAN_TOKEN" not in os.environ
    assert FAKE_TOKEN not in repr(s)


def test_real_environment_wins_over_dotenv(dotenv, monkeypatch):
    dotenv.write_text("BG_FIREBASE_PROJECT_ID=from-file\n", encoding="utf-8")
    monkeypatch.setenv("BG_FIREBASE_PROJECT_ID", "from-shell")
    assert config.load_settings().firebase_project_id == "from-shell"


def test_dotenv_does_not_modify_os_environ(dotenv):
    dotenv.write_text("BG_ADMIN_EMAILS=a@x.com\n", encoding="utf-8")
    config.load_settings()
    assert "BG_ADMIN_EMAILS" not in os.environ


@pytest.mark.parametrize("text,expected", [
    ("# comment\n\nBG_ENVIRONMENT=x\n", {"BG_ENVIRONMENT": "x"}),
    ('BG_ENVIRONMENT="quoted value"\n', {"BG_ENVIRONMENT": "quoted value"}),
    ("BG_ENVIRONMENT='single'\n", {"BG_ENVIRONMENT": "single"}),
    ("export BG_ENVIRONMENT=x\n", {"BG_ENVIRONMENT": "x"}),
    ("  BG_ENVIRONMENT = spaced  \r\n", {"BG_ENVIRONMENT": "spaced"}),
    ("BG_ENVIRONMENT=x # trailing comment\n", {"BG_ENVIRONMENT": "x"}),
    ("not a pair\nBG_=empty-name\nbg_environment=lower\n", {}),
    ("﻿BG_ENVIRONMENT=bom\n", {"BG_ENVIRONMENT": "bom"}),
])
def test_parsing(dotenv, text, expected):
    dotenv.write_text(text, encoding="utf-8")
    assert config.read_dotenv_bg(dotenv) == expected


def test_missing_file_is_fine(dotenv):
    assert not dotenv.exists()
    assert config.read_dotenv_bg(dotenv) == {}
    assert config.load_settings().firebase_project_id is None


def test_opt_out_ignores_the_file(dotenv, monkeypatch):
    dotenv.write_text("BG_FIREBASE_PROJECT_ID=argus-demo\n", encoding="utf-8")
    monkeypatch.setenv("BG_NO_DOTENV", "1")
    assert config.load_settings().firebase_project_id is None


def test_default_path_is_repo_root_dotenv(monkeypatch):
    monkeypatch.delenv("BG_DOTENV_FILE", raising=False)
    assert config.dotenv_path() == config.REPO_ROOT / ".env"


def test_bg_env_helper_reads_dotenv_and_skips_non_bg(dotenv):
    dotenv.write_text("BG_API_URL=http://127.0.0.1:9001\nDIGITALOCEAN_TOKEN=x\n", encoding="utf-8")
    assert config.bg_env("BG_API_URL") == "http://127.0.0.1:9001"
    assert config.bg_env("BG_DO_TOKEN_FILE", "fallback") == "fallback"
    with pytest.raises(ValueError):
        config.bg_env("DIGITALOCEAN_TOKEN")
