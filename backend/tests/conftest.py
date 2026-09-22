"""DB fixtures: a throwaway `<db>_test` database, migrated once per run.

Every test runs inside a transaction that is rolled back, so tests never see each other's rows.
Requires the compose Postgres: `make db-up` (or `make up`).
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.db.session import get_session
from app.main import create_app

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


@pytest.fixture
async def committing_session_factory(
    migrated_db_url: URL,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions that really commit (for code that opens its own transaction). Tests using this
    must clean up the rows they create."""
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(get_settings().redis_url)
    try:
        await client.ping()
    except (RedisError, OSError) as exc:
        pytest.exit(f"Redis is not reachable ({exc}). Start it with `make redis-up`.", 1)
    yield client
    await client.aclose()


@pytest.fixture
def key_prefix() -> str:
    """A unique Redis key prefix per test, so tests never share limiter/cache state."""
    return f"test:{uuid.uuid4().hex}:"


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """The real app, with its DB dependency swapped for the rolled-back test session."""
    app = create_app()

    async def use_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = use_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
