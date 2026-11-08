"""Runtime configuration from environment variables.

Security notes:
- The Terraform working directory is fixed by server-side configuration
  (BG_TF_DIR) and must resolve inside one of the repository's Terraform roots
  (break-glass-infra/) unless BG_ALLOW_TF_DIR_OUTSIDE_REPO=1 is set. It is never taken from HTTP input.
- No cloud credential is read or stored here. Terraform reads DIGITALOCEAN_TOKEN
  from its own environment.
- Settings may also come from the repo-root .env (override the path with
  BG_DOTENV_FILE, disable with BG_NO_DOTENV=1). Only keys starting with BG_ are
  read; every other line (e.g. DIGITALOCEAN_TOKEN) is ignored and never stored.
  Values already in the real environment win. os.environ is never modified.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_TF_DIR = REPO_ROOT / "break-glass-infra"
ALLOWED_TF_ROOTS = (REPO_ROOT / "break-glass-infra",)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    db_path: Path
    tf_dir: Path | None
    environment: str
    cors_origins: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    terraform_bin: str
    # Shared admin bearer token for /api/admin/*. Never logged or echoed; unset or blank = admin API disabled.
    admin_token: str | None = field(default=None, repr=False)
    # Firebase (Google) sign-in. The project id is a PUBLIC identifier, not a secret.
    # Set = web writes require sign-in; admin log also accepts listed admin emails.
    firebase_project_id: str | None = None
    admin_emails: tuple[str, ...] = ()
    # Demo mode: every verified Google sign-in is an admin (BG_ALL_ADMINS=1). Admin screens are read-only.
    all_admins: bool = False
    # PostgreSQL / Tiger Cloud DSN. Secret: never logged, echoed or committed. Unset = explicit SQLite mode.
    database_url: str | None = field(default=None, repr=False)


def _database_url(raw: str | None) -> str | None:
    """BG_DATABASE_URL selects PostgreSQL (Tiger Cloud). Validation errors never echo the value."""
    from urllib.parse import urlsplit
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        u = urlsplit(raw)
        ok = u.scheme in ("postgresql", "postgres") and bool(u.hostname) and u.path.strip("/") != ""
    except ValueError:
        ok = False
    if not ok:
        raise ConfigError("BG_DATABASE_URL must look like postgresql://user:password@host:port/dbname (value hidden)")
    return raw


def dotenv_path() -> Path:
    return Path(os.environ.get("BG_DOTENV_FILE") or REPO_ROOT / ".env")


def read_dotenv_bg(path: Path) -> dict[str, str]:
    """BG_* key/value pairs from a .env file. Other keys are skipped without being kept."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return {}
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if not line.startswith("BG_") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if len(key) <= 3 or not all(c.isupper() or c.isdigit() or c == "_" for c in key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def _environ() -> dict[str, str]:
    if os.environ.get("BG_NO_DOTENV") == "1":
        return dict(os.environ)
    return {**read_dotenv_bg(dotenv_path()), **os.environ}


def bg_env(key: str, default: str | None = None) -> str | None:
    """One BG_* setting, from the real environment or the repo-root .env."""
    if not key.startswith("BG_"):
        raise ValueError("bg_env only reads BG_* settings")
    return _environ().get(key, default)


def _resolve_tf_dir(raw: str | None, env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    path = Path(raw).expanduser() if raw else DEFAULT_TF_DIR
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not path.is_dir():
        return None
    if env.get("BG_ALLOW_TF_DIR_OUTSIDE_REPO") != "1":
        roots = [r.resolve() for r in ALLOWED_TF_ROOTS]
        if not any(path == r or r in path.parents for r in roots):
            raise ConfigError("BG_TF_DIR must be inside " + " or ".join(str(r) for r in roots))
    return path


def load_settings() -> Settings:
    env = _environ()
    origins = env.get("BG_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        db_path=Path(env.get("BG_DB_PATH", BACKEND_DIR / "breakglass.db")),
        tf_dir=_resolve_tf_dir(env.get("BG_TF_DIR"), env),
        environment=env.get("BG_ENVIRONMENT", "demo"),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        allowed_hosts=tuple(h.strip() for h in env.get(
            "BG_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()),
        # Absolute path so Windows never runs a terraform.exe found in the current directory.
        terraform_bin=shutil.which(env.get("BG_TERRAFORM_BIN", "terraform")) or "terraform",
        admin_token=env.get("BG_ADMIN_TOKEN") or None,
        firebase_project_id=(env.get("BG_FIREBASE_PROJECT_ID") or "").strip() or None,
        admin_emails=tuple(e.strip().lower() for e in env.get("BG_ADMIN_EMAILS", "").split(",")
                           if e.strip()),
        all_admins=(env.get("BG_ALL_ADMINS") or "").strip().lower() in ("1", "true", "yes"),
        database_url=_database_url(env.get("BG_DATABASE_URL")),
    )
