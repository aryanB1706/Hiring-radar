"""DB fixtures: a throwaway `<db>_test` database, migrated once per run.

Every test runs inside a transaction that is rolled back, so tests never see each other's rows.
Requires the compose Postgres: `make db-up` (or `make up`).
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _recreate_database(admin_url: URL, name: str) -> None:
    assert name.endswith("_test"), "refusing to drop a database that is not a *_test database"
    admin = create_engine(admin_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as exc:
        pytest.exit(f"Postgres is not reachable ({exc.orig}). Start it with `make db-up`.", 1)
    finally:
        admin.dispose()


def migrate(url: URL, revision: str = "head") -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    command.upgrade(cfg, revision)


def alembic_config(url: URL) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    return cfg


def database_url_for(suffix: str = "") -> URL:
    base = make_url(get_settings().database_url)
    return base.set(database=f"{base.database}{suffix}_test")


@pytest.fixture(scope="session")
def migrated_db_url() -> Iterator[URL]:
    url = database_url_for()
    _recreate_database(url, url.database or "")
    migrate(url)
    yield url


@pytest.fixture
async def session(migrated_db_url: URL) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        async with AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as s:
            yield s
        await outer.rollback()
    await engine.dispose()
