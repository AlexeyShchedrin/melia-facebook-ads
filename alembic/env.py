"""Alembic env.py — uses FB_DATABASE_URL and operates only on schema `meta`."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from meta_ads.config import get_settings
from meta_ads.db.models import SCHEMA, Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _sync_url() -> str:
    """Normalize to the psycopg (v3) driver — drives both Alembic's sync engine
    and the app's async engine, so we never fall through to psycopg2."""
    url = get_settings().fb_database_url
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://")


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    if type_ == "schema":
        return name == SCHEMA
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    # The `meta` schema itself is a bootstrap artifact created once by a superuser
    # (`CREATE SCHEMA meta AUTHORIZATION fb_svc`). Alembic only manages tables
    # within it, so fb_svc needs no database-level CREATE privilege.
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema=SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
