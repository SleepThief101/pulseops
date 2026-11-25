from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect


def test_alembic_head_matches_test_database(test_engine):
    """Verify current test database revision matches Alembic migration head."""
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    head_rev = script.get_current_head()

    with test_engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()

    assert head_rev is not None
    assert current_rev == head_rev


def test_test_database_tables_exist_via_inspector(test_engine):
    """Verify all four tables exist in PostgreSQL test database via SQLAlchemy inspector."""
    inspector = inspect(test_engine)
    table_names = set(inspector.get_table_names())

    expected = {
        "organizations",
        "users",
        "memberships",
        "integrations",
        "events",
        "sync_runs",
        "action_proposals",
        "audit_logs",
        "api_keys",
        "webhook_deliveries",
        "alembic_version",
    }
    assert expected.issubset(table_names)
