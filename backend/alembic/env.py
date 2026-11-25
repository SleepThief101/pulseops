import socket
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

from app.config import normalize_database_url, settings
from app.db.base import Base
import app.models  # noqa: F401 - Register all models with Base.metadata

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata


def get_url() -> str:
    """
    Retrieve the database connection URL from Pydantic Settings.
    If running outside the Docker Compose network and the 'db' service hostname
    is unresolvable, dynamically adapt to localhost/127.0.0.1.
    """
    url = normalize_database_url(settings.database_url)
    if "@db:" in url:
        try:
            socket.gethostbyname("db")
        except (socket.gaierror, OSError):
            url = url.replace("@db:", "@127.0.0.1:")
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
