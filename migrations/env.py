"""Alembic environment for the Phase 2 PostgreSQL schema baseline."""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path
from urllib.parse import quote_plus

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = MetaData(schema="app")


def database_url() -> str:
    """Build the migration URL from non-secret fields and a protected file."""

    host = os.environ.get("PHASE2_POSTGRES_HOST", "127.0.0.1")
    port = int(os.environ.get("PHASE2_POSTGRES_PORT", "5432"))
    user = os.environ.get("PHASE2_POSTGRES_USER", "ntc_app")
    database = os.environ.get("PHASE2_POSTGRES_DB", "ntc_rag")
    password_file = Path(
        os.environ.get(
            "PHASE2_POSTGRES_PASSWORD_FILE",
            ".secrets/phase2/postgres_password",
        )
    )
    try:
        password = password_file.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError("unable to read the PostgreSQL password file") from error
    if not password:
        raise RuntimeError("PostgreSQL password file must not be empty")

    return (
        "postgresql+psycopg://"
        f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{quote_plus(database)}"
    )


def run_migrations_offline() -> None:
    """Render migrations without establishing a database connection."""

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations through a bounded SQLAlchemy engine."""

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 5},
    )
    with connectable.connect() as connection:
        # Every application query intentionally uses the ``app`` namespace. Do
        # not depend on a machine-specific role setting when bootstrapping a new
        # database or running migrations from another host.
        connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS app")
        connection.exec_driver_sql("SET search_path TO app, public")
        # The statements above autobegin in SQLAlchemy 2. Commit that setup so
        # Alembic can own and commit its migration transaction normally.
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            version_table_schema="app",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
