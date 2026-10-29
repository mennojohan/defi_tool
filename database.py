"""
Async database connection en session management
Ondersteunt SQLite (dev) en PostgreSQL (prod)
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
)
from sqlalchemy.pool import NullPool, QueuePool

from models import Base

logger = logging.getLogger(__name__)


class Database:
    """
    Database connection manager met async support
    
    Usage:
        db = Database("sqlite+aiosqlite:///./defi_tracker.db")
        await db.init()
        
        async with db.session() as session:
            session.add(swap)
            await session.commit()
    """
    
    def __init__(
        self,
        database_url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10
    ):
        """
        Args:
            database_url: SQLAlchemy connection string
                - SQLite: "sqlite+aiosqlite:///./defi_tracker.db"
                - PostgreSQL: "postgresql+asyncpg://user:pass@localhost/dbname"
            echo: Log alle SQL queries (debug mode)
            pool_size: Connection pool size (niet voor SQLite)
            max_overflow: Max extra connections (niet voor SQLite)
        """
        self.database_url = database_url
        self.echo = echo
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        
        # SQLite heeft geen connection pooling nodig
        self.is_sqlite = "sqlite" in database_url.lower()
        self.pool_size = pool_size if not self.is_sqlite else 0
        self.max_overflow = max_overflow if not self.is_sqlite else 0
    
    async def init(self) -> None:
        """
        Initialize database engine en maak tabellen
        Call dit eenmalig bij app startup
        """
        logger.info(f"Initializing database: {self.database_url}")
        
        # Create async engine
        if self.is_sqlite:
            # SQLite: gebruik NullPool (geen pooling)
            self._engine = create_async_engine(
                self.database_url,
                echo=self.echo,
                poolclass=NullPool,
                # SQLite-specific: enable foreign keys
                connect_args={"check_same_thread": False}
            )
        else:
            # PostgreSQL: gebruik connection pooling
            self._engine = create_async_engine(
                self.database_url,
                echo=self.echo,
                poolclass=QueuePool,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_pre_ping=True,  # Verify connections voor gebruik
            )
        
        # Create session factory
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,  # Objecten blijven usable na commit
        )
        
        # Create tables (idempotent)
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Database initialized successfully")
    
    async def close(self) -> None:
        """Sluit database connecties netjes af"""
        if self._engine:
            await self._engine.dispose()
            logger.info("Database connections closed")
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Context manager voor database sessies
        
        Usage:
            async with db.session() as session:
                session.add(obj)
                await session.commit()
        """
        if not self._session_factory:
            raise RuntimeError("Database not initialized. Call await db.init() first")
        
        async with self._session_factory() as session:
            try:
                yield session
            except Exception as e:
                await session.rollback()
                logger.error(f"Session error, rolled back: {e}")
                raise
            finally:
                await session.close()
    
    @property
    def engine(self) -> AsyncEngine:
        """Get the async engine (voor advanced gebruik)"""
        if not self._engine:
            raise RuntimeError("Database not initialized")
        return self._engine


# Singleton instance (import deze in andere modules)
_db_instance: Database | None = None


def get_database(database_url: str | None = None, **kwargs) -> Database:
    """
    Get or create database singleton
    
    Args:
        database_url: Connection string (alleen eerste keer nodig)
        **kwargs: Extra args voor Database constructor
    
    Returns:
        Database instance
    """
    global _db_instance
    
    if _db_instance is None:
        if database_url is None:
            raise ValueError("database_url required for first call")
        _db_instance = Database(database_url, **kwargs)
    
    return _db_instance


async def init_database(database_url: str, **kwargs) -> Database:
    """
    Initialize database (call bij startup)
    
    Usage:
        db = await init_database("sqlite+aiosqlite:///./defi_tracker.db")
    """
    db = get_database(database_url, **kwargs)
    await db.init()
    return db
