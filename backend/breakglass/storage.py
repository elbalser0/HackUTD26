"""Backend selection. BG_DATABASE_URL set -> PostgreSQL (Tiger Cloud); unset -> SQLite at BG_DB_PATH.

There is no fallback: a configured PostgreSQL that cannot be reached is an error, never a silent
switch to a local file (that would split the audit history across two stores).
"""

from __future__ import annotations

from typing import Union

from .config import Settings
from .db import Database


class StorageUnavailable(RuntimeError):
    """The configured database cannot be used. The message never contains the DSN or driver detail."""


def open_database(settings: Settings) -> Union[Database, "PostgresDatabase"]:  # noqa: F821
    if settings.database_url is None:
        return Database(settings.db_path)
    from .postgres import PostgresDatabase
    return PostgresDatabase(settings.database_url)
