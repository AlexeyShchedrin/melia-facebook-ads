from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from meta_ads.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.fb_database_url,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    # Fail fast if the DB is unreachable (e.g. running the CLI/MCP locally with no
    # `meta` Postgres) so get_token / caches fall back to .env within seconds
    # instead of hanging on the TCP connect.
    connect_args={"connect_timeout": 2},
)

async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session
