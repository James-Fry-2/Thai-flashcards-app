from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import event
from src.config.settings import get_settings

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        kwargs = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            # timeout=15: retry for up to 15 s when another connection holds a write lock
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
        _engine = create_async_engine(url, **kwargs)

        if url.startswith("sqlite"):
            # WAL mode lets readers and a writer coexist; cuts lock contention
            # between background upload tasks and foreground review sessions.
            @event.listens_for(_engine.sync_engine, "connect")
            def _set_wal(dbapi_conn, _rec):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _session_factory


async def get_db():
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
