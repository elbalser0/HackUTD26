"""Production launch must never silently use local demo defaults."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def startup():
    path = Path(__file__).resolve().parents[2] / "deploy" / "api_start.py"
    spec = importlib.util.spec_from_file_location("api_start", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("env", [
    {},
    {"BG_DATABASE_URL": "postgresql://private-value"},
    {"BG_FIREBASE_PROJECT_ID": "project"},
    {"BG_DATABASE_URL": " ", "BG_FIREBASE_PROJECT_ID": "project"},
])
def test_missing_settings_fail_closed(startup, env):
    with pytest.raises(SystemExit) as exc:
        startup.validate(env)
    assert "private-value" not in str(exc.value)
    assert "required" in str(exc.value)


def test_configured_startup(startup):
    startup.validate({"BG_DATABASE_URL": "postgresql://provided", "BG_FIREBASE_PROJECT_ID": "project"})
