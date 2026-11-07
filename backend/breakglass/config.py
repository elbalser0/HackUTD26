"""Runtime configuration from environment variables.

Security notes:
- The Terraform working directory is fixed by server-side configuration
  (BG_TF_DIR) and must resolve inside the repository's infra/ tree unless
  BG_ALLOW_TF_DIR_OUTSIDE_REPO=1 is set. It is never taken from HTTP input.
- No credential is read or stored here. Terraform reads DIGITALOCEAN_TOKEN
  from its own environment.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
DEFAULT_TF_DIR = REPO_ROOT / "infra" / "demo"
ALLOWED_TF_ROOT = REPO_ROOT / "infra"


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


def _resolve_tf_dir(raw: str | None) -> Path | None:
    path = Path(raw).expanduser() if raw else DEFAULT_TF_DIR
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError:
        return None
    if not path.is_dir():
        return None
    if os.environ.get("BG_ALLOW_TF_DIR_OUTSIDE_REPO") != "1":
        allowed = ALLOWED_TF_ROOT.resolve()
        if path != allowed and allowed not in path.parents:
            raise ConfigError(f"BG_TF_DIR must be inside {allowed}")
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
    )
