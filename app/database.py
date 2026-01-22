"""Database connection and session management."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


def create_db_engine():
    """Create SQLAlchemy engine with connection pooling."""
    settings = get_settings()

    engine = create_engine(
        settings.database_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # Verify connections before using
        echo=False,  # Set to True for SQL debugging
    )
    return engine


# Create engine and session factory
engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency for FastAPI endpoints that need a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions.

    Usage:
        with get_db_session() as db:
            db.query(...)
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_health() -> bool:
    """Verify database connection is working.

    Returns:
        True if database is healthy, False otherwise.
    """
    try:
        with get_db_session() as db:
            db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"Database health check failed: {e}")
        return False


def dispose_engine() -> None:
    """Dispose of the engine and all connections.

    Call this during graceful shutdown.
    """
    engine.dispose()


def list_tables() -> list[str]:
    """List all tables in the database.

    Returns:
        List of table names.
    """
    try:
        with get_db_session() as db:
            result = db.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return [row[0] for row in result.fetchall()]
    except Exception as e:
        print(f"Failed to list tables: {e}")
        return []
