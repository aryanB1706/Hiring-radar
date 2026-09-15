from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

from app.db.base import Base
from tests.conftest import _recreate_database, alembic_config, database_url_for


def _tables(url: URL) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_and_models_match_migration() -> None:
    url = database_url_for("_migrations")
    _recreate_database(url, url.database or "")
    cfg = alembic_config(url)

    command.upgrade(cfg, "head")
    assert len(_tables(url)) == 12

    # Models and migration describe the same schema.
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
        assert diff == []
    engine.dispose()

    command.downgrade(cfg, "base")
    assert _tables(url) == set()
    engine = create_engine(url)
    with engine.connect() as conn:
        extensions = conn.execute(text("SELECT extname FROM pg_extension")).scalars().all()
        assert "vector" not in extensions
    engine.dispose()

    command.upgrade(cfg, "head")
    assert len(_tables(url)) == 12
