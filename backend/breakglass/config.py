"""Runtime configuration from environment variables.

Security notes:
- The Terraform working directory is fixed by server-side configuration
  (BG_TF_DIR) and must resolve inside one of the repository's Terraform roots
  (break-glass-infra/) unless BG_ALLOW_TF_DIR_OUTSIDE_REPO=1 is set. It is never taken from HTTP input.
- No credential is read or stored here. Terraform reads DIGITALOCEAN_TOKEN
  from its own environment.
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


def _resolve_tf_dir(raw: str | None) -> Path | None:
    path = Path(raw).expanduser() if raw else DEFAULT_TF_DIR
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not path.is_dir():
        return None
    if os.environ.get("BG_ALLOW_TF_DIR_OUTSIDE_REPO") != "1":
        roots = [r.resolve() for r in ALLOWED_TF_ROOTS]
        if not any(path == r or r in path.parents for r in roots):
            raise ConfigError("BG_TF_DIR must be inside " + " or ".join(str(r) for r in roots))
    return path


def load_settings() -> Settings:
    origins = os.environ.get("BG_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        db_path=Path(os.environ.get("BG_DB_PATH", BACKEND_DIR / "breakglass.db")),
        tf_dir=_resolve_tf_dir(os.environ.get("BG_TF_DIR")),
        environment=os.environ.get("BG_ENVIRONMENT", "demo"),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        allowed_hosts=tuple(h.strip() for h in os.environ.get(
            "BG_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()),
        # Absolute path so Windows never runs a terraform.exe found in the current directory.
        terraform_bin=shutil.which(os.environ.get("BG_TERRAFORM_BIN", "terraform")) or "terraform",
        admin_token=os.environ.get("BG_ADMIN_TOKEN") or None,
        firebase_project_id=(os.environ.get("BG_FIREBASE_PROJECT_ID") or "").strip() or None,
        admin_emails=tuple(e.strip().lower() for e in os.environ.get("BG_ADMIN_EMAILS", "").split(",")
                           if e.strip()),
        database_url=_database_url(os.environ.get("BG_DATABASE_URL")),
    )
