"""
Automated Microsoft SQL Server Database Provisioning Utility.

Connects to MS SQL Server 'master' database, creates the target database
with snapshot isolation enabled, initializes the schema, and optionally
migrates existing data from SQLite/PostgreSQL.

Usage:
    python -m backend.app.scripts.create_mssql_db
    python -m backend.app.scripts.create_mssql_db --host localhost --user sa --password MyPassword
    python -m backend.app.scripts.create_mssql_db --migrate-from-sqlite
"""

import argparse
import logging
import sys
import urllib.parse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import Base, configure_engine
from backend.app.db.init_db import init_db
from backend.app.scripts.migrate_to_mssql import migrate_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("create_mssql_db")


def create_mssql_database(
    host: str,
    port: int = 1433,
    database: str = "Garant_MPP_hub",
    user: str = "",
    password: str = "",
    trusted_connection: bool = False,
    driver: str = "ODBC Driver 18 for SQL Server",
    init_schema: bool = True,
    seed_defaults: bool = False,
    migrate_source: str = "",
) -> None:
    # 1. Build master connection URL (connecting to 'master' database to run CREATE DATABASE)
    if trusted_connection:
        driver_clean = driver.replace(" ", "+")
        master_url = f"mssql+pyodbc://@{host}:{port}/master?driver={driver_clean}&trusted_connection=yes&TrustServerCertificate=yes"
        target_url = f"mssql+pyodbc://@{host}:{port}/{database}?driver={driver_clean}&trusted_connection=yes&TrustServerCertificate=yes"
    else:
        user_enc = urllib.parse.quote_plus(user)
        pwd_enc = urllib.parse.quote_plus(password)
        master_url = f"mssql+pymssql://{user_enc}:{pwd_enc}@{host}:{port}/master"
        target_url = f"mssql+pymssql://{user_enc}:{pwd_enc}@{host}:{port}/{database}"

    logger.info("Connecting to MS SQL Server at %s:%d (master database)...", host, port)
    master_engine = configure_engine(master_url)

    # In MSSQL, CREATE DATABASE cannot execute inside a multi-statement transaction
    with master_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        logger.info("Checking if database [%s] exists...", database)
        check_query = text("SELECT database_id FROM sys.databases WHERE name = :db_name")
        res = conn.execute(check_query, {"db_name": database}).scalar()

        if not res:
            logger.info("Database [%s] does not exist. Creating database...", database)
            conn.execute(text(f"CREATE DATABASE [{database}]"))
            logger.info("Database [%s] created successfully.", database)
        else:
            logger.info("Database [%s] already exists.", database)

        # Enable Read Committed Snapshot Isolation (avoids lock contention)
        logger.info("Enabling READ_COMMITTED_SNAPSHOT on [%s]...", database)
        try:
            conn.execute(text(f"ALTER DATABASE [{database}] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE"))
            conn.execute(text(f"ALTER DATABASE [{database}] SET ALLOW_SNAPSHOT_ISOLATION ON"))
            logger.info("Snapshot isolation configured successfully.")
        except Exception as e:
            logger.warning("Could not set snapshot isolation (may already be in use): %s", e)

    master_engine.dispose()

    # 2. Connect to the newly created / verified target database
    logger.info("Connecting to target database [%s]...", database)
    target_engine = configure_engine(target_url)

    if init_schema:
        logger.info("Creating schema tables on [%s]...", database)
        Base.metadata.create_all(bind=target_engine)
        logger.info("All schema tables verified / created successfully.")

    if migrate_source:
        logger.info("Migrating data from source [%s] to MS SQL Server...", migrate_source)
        report = migrate_database(
            source_url=migrate_source,
            target_url=target_url,
            init_schema=False,
            dry_run=False,
        )
        logger.info("Data migration completed. Status: %s. Rows migrated: %d", report["status"], report["total_rows_migrated"])
    elif seed_defaults:
        logger.info("Seeding default master data into [%s]...", database)
        with Session(target_engine) as session:
            init_db(session)
        logger.info("Default master data seeded successfully.")

    target_engine.dispose()
    logger.info("Database provisioning complete! Connection string to add to .env:")
    logger.info("  DATABASE_URL=%s", target_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and configure MPP Hub database on Microsoft SQL Server")
    parser.add_argument("--host", type=str, default=None, help="MS SQL Server host/IP (defaults to MSSQL_HOST in .env)")
    parser.add_argument("--port", type=int, default=settings.MSSQL_PORT or 1433, help="MS SQL Server port (default: 1433)")
    parser.add_argument("--database", type=str, default=settings.MSSQL_DATABASE or "Garant_MPP_hub", help="Database name to create (default: Garant_MPP_hub)")
    parser.add_argument("--user", type=str, default=None, help="SQL Server username (defaults to MSSQL_USER in .env)")
    parser.add_argument("--password", type=str, default=None, help="SQL Server password (defaults to MSSQL_PASSWORD in .env)")
    parser.add_argument("--trusted-connection", action="store_true", help="Use Windows Authentication instead of SQL Auth")
    parser.add_argument("--driver", type=str, default="ODBC Driver 18 for SQL Server", help="ODBC Driver name for pyodbc")
    parser.add_argument("--no-init-schema", action="store_true", help="Do not create tables")
    parser.add_argument("--seed", action="store_true", help="Seed default master data (calendars, resources, etc.)")
    parser.add_argument("--migrate-from-sqlite", action="store_true", help="Migrate data from current local SQLite database")

    args = parser.parse_args()

    host = args.host or settings.MSSQL_HOST
    user = args.user if args.user is not None else settings.MSSQL_USER
    password = args.password if args.password is not None else settings.MSSQL_PASSWORD
    trusted = args.trusted_connection or settings.MSSQL_TRUSTED_CONNECTION
    driver = args.driver or settings.MSSQL_DRIVER

    if not host and not trusted:
        print("Error: MS SQL Server host must be provided via --host or MSSQL_HOST in .env", file=sys.stderr)
        sys.exit(1)

    migrate_source = "sqlite:///./mpp_hub.db" if args.migrate_from_sqlite else ""

    try:
        create_mssql_database(
            host=host,
            port=args.port,
            database=args.database,
            user=user,
            password=password,
            trusted_connection=trusted,
            driver=driver,
            init_schema=not args.no_init_schema,
            seed_defaults=args.seed,
            migrate_source=migrate_source,
        )
    except Exception as e:
        logger.exception("Failed to provision MS SQL Server database: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
