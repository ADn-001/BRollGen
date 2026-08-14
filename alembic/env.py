import sys
from pathlib import Path

# Add backend/ to sys.path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.database import DATABASE_URL
from db import models  # noqa: F401 — ensure all models are registered on Base.metadata
from db.database import Base

config = context.config

# Override ini URL with the absolute path from code (handles different CWDs)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a DB connection (generates SQL script)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
