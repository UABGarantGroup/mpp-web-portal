"""
Database session and connection management for SQLAlchemy 2.0.
Supports SQLite (local dev), PostgreSQL (production container),
and Microsoft SQL Server (pyodbc / pymssql).
"""

from typing import Any, Dict, Generator, Optional
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.types import String, Text

from backend.app.core.config import settings


# Ensure Microsoft SQL Server always maps String and Text to Unicode types (NVARCHAR),
# preventing Baltic/Nordic and international character encoding corruption (mojibake).
@compiles(String, "mssql")
def _compile_string_mssql(type_, compiler, **kw):
    if type_.length:
        return f"NVARCHAR({type_.length})"
    return "NVARCHAR(MAX)"


@compiles(Text, "mssql")
def _compile_text_mssql(type_, compiler, **kw):
    return "NVARCHAR(MAX)"



def configure_engine(url: Optional[str] = None) -> Engine:
    """
    Creates and configures a dialect-aware SQLAlchemy engine.
    Supports SQLite, PostgreSQL, and Microsoft SQL Server (pyodbc / pymssql).
    """
    db_url = url or settings.DATABASE_URL
    connect_args: Dict[str, Any] = {}
    engine_kwargs: Dict[str, Any] = {
        "pool_pre_ping": True,
    }

    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    elif db_url.startswith("postgresql+psycopg://"):
        try:
            import psycopg  # noqa: F401
        except ImportError:
            db_url = db_url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    elif db_url.startswith("mssql"):
        # Microsoft SQL Server optimizations
        if "pyodbc" in db_url or db_url.startswith("mssql://"):
            engine_kwargs["fast_executemany"] = True
            # If driver not explicitly in query parameters, attempt to select installed driver
            if "driver=" not in db_url.lower():
                try:
                    import pyodbc
                    installed_drivers = pyodbc.drivers()
                    preferred = [
                        "ODBC Driver 18 for SQL Server",
                        "ODBC Driver 17 for SQL Server",
                        "ODBC Driver 13 for SQL Server",
                        "SQL Server",
                    ]
                    chosen_driver = next((d for d in preferred if d in installed_drivers), None)
                    if chosen_driver:
                        sep = "&" if "?" in db_url else "?"
                        trust = "&TrustServerCertificate=yes" if ("18" in chosen_driver and "trustservercertificate" not in db_url.lower()) else ""
                        db_url = f"{db_url}{sep}driver={chosen_driver.replace(' ', '+')}{trust}"
                except Exception:
                    pass

    return create_engine(
        db_url,
        connect_args=connect_args,
        **engine_kwargs,
    )


engine = configure_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator:
    """
    FastAPI dependency yielding a SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
