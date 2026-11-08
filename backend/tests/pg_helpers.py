"""Disposable-schema helpers for PostgreSQL tests. Only ever touch schemas named bgtest_*."""

from __future__ import annotations

import secrets

import psycopg

from breakglass.postgres import migrate


def migrate_test_schema(url: str) -> str:
    schema = "bgtest_" + secrets.token_hex(4)
    migrate(url, schema)
    return schema


def drop_test_schema(url: str, schema: str) -> None:
    assert schema.startswith("bgtest_"), "refusing to drop a non-test schema"
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
