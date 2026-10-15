"""
Database Migration Utility: Source (SQLite/PostgreSQL) to Microsoft SQL Server.

Features:
- Preserves all primary keys, UUIDs, foreign key relationships, and rate chronologies.
- Dialect-aware: uses SET IDENTITY_INSERT ON/OFF for MS SQL Server identity tables.
- Topological dependency order to satisfy all foreign key constraints.
- Batch chunking for high performance.
- Dry-run validation and row-count integrity checking.
"""

import argparse
import logging
import sys
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine

from backend.app.core.config import settings
from backend.app.db.session import Base, configure_engine
import backend.app.db.models  # Registers all SQLAlchemy ORM models

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mssql_migration")

# Strict foreign-key topological order for data transfer
ORDERED_TABLE_NAMES = [
    "calendars",
    "calendar_weekdays",
    "calendar_working_shifts",
    "calendar_exceptions",
    "resources",
    "rate_periods",
    "custom_fields",
    "field_lookup_values",
    "resource_field_values",
    "projects",
    "stage_definitions",
    "project_stage_statuses",
    "project_snapshots",
    "project_team_resources",
    "portal_users",
    "audit_logs",
]


def has_identity_primary_key(table: Any) -> bool:
    """
    Checks if a table has an integer primary key column that behaves as
    an IDENTITY column in Microsoft SQL Server.
    """
    for col in table.primary_key.columns:
        if str(col.type).lower().startswith("int") or getattr(col, "autoincrement", False) is True:
            return True
    return False


def migrate_database(
    source_url: Optional[str] = None,
    target_url: Optional[str] = None,
    dry_run: bool = False,
    init_schema: bool = True,
    batch_size: int = 500,
    source_engine: Optional[Engine] = None,
    target_engine: Optional[Engine] = None,
) -> Dict[str, Any]:
    """
    Migrates all table data from source to target MS SQL Server database.
    """
    tgt_url = target_url or (settings.DATABASE_URL if not target_engine else "")
    src_url = source_url or ("sqlite:///./mpp_hub.db" if (tgt_url and not tgt_url.startswith("sqlite")) else settings.DATABASE_URL)

    if not tgt_url and not target_engine:
        raise ValueError("Target database URL or target_engine must be provided.")

    src_engine = source_engine or configure_engine(src_url)
    tgt_engine = target_engine or configure_engine(tgt_url)

    target_dialect_name = tgt_engine.dialect.name
    is_mssql = (target_dialect_name == "mssql")

    logger.info("Starting database migration:")
    logger.info("  Source: %s (dialect: %s)", src_url if not source_engine else "<custom_engine>", src_engine.dialect.name)
    logger.info("  Target: %s (dialect: %s)", target_url if not target_engine else "<custom_engine>", target_dialect_name)
    logger.info("  Dry-Run: %s | Init Schema: %s", dry_run, init_schema)

    # 1. Initialize schema on target if requested
    if init_schema and not dry_run:
        logger.info("Creating target schema tables from Base.metadata...")
        Base.metadata.create_all(bind=tgt_engine)
        logger.info("Schema tables created / verified on target database.")

    report: Dict[str, Any] = {
        "status": "DRY_RUN" if dry_run else "SUCCESS",
        "source_dialect": src_engine.dialect.name,
        "target_dialect": target_dialect_name,
        "tables": {},
        "total_rows_migrated": 0,
    }

    # 2. Iterate tables in topological order
    with src_engine.connect() as src_conn:
        with tgt_engine.connect() as tgt_conn:
            for table_name in ORDERED_TABLE_NAMES:
                table = Base.metadata.tables.get(table_name)
                if table is None:
                    logger.warning("Table '%s' not found in Base.metadata. Skipping.", table_name)
                    continue

                # Read source rows
                try:
                    src_rows = src_conn.execute(select(table)).mappings().all()
                except Exception as e:
                    logger.warning("Failed to query source table '%s' (might not exist yet): %s", table_name, e)
                    continue

                records = [dict(r) for r in src_rows]
                row_count = len(records)
                logger.info("Table '%s': %d rows found in source.", table_name, row_count)

                table_report = {
                    "source_rows": row_count,
                    "target_rows": 0,
                    "status": "SKIPPED_EMPTY" if row_count == 0 else "PENDING",
                }

                if row_count == 0:
                    report["tables"][table_name] = table_report
                    continue

                if dry_run:
                    table_report["status"] = "DRY_RUN_OK"
                    report["tables"][table_name] = table_report
                    continue

                # Target insertion
                has_ident = is_mssql and has_identity_primary_key(table)

                try:
                    # In MSSQL, explicit PK insertion requires IDENTITY_INSERT ON
                    if has_ident:
                        tgt_conn.execute(text(f"SET IDENTITY_INSERT [{table.name}] ON"))

                    # Batch insert
                    for i in range(0, row_count, batch_size):
                        chunk = records[i:i + batch_size]
                        tgt_conn.execute(table.insert(), chunk)

                    if has_ident:
                        tgt_conn.execute(text(f"SET IDENTITY_INSERT [{table.name}] OFF"))

                    tgt_conn.commit()

                    # Verify target count
                    tgt_count = tgt_conn.execute(select(func.count()).select_from(table)).scalar()
                    table_report["target_rows"] = tgt_count
                    table_report["status"] = "OK" if tgt_count >= row_count else "MISMATCH"
                    report["total_rows_migrated"] += row_count
                    logger.info("Table '%s': migrated %d rows successfully (target count: %d).", table_name, row_count, tgt_count)

                except Exception as insert_err:
                    if has_ident:
                        try:
                            tgt_conn.execute(text(f"SET IDENTITY_INSERT [{table.name}] OFF"))
                        except Exception:
                            pass
                    tgt_conn.rollback()
                    logger.error("Error migrating table '%s': %s", table_name, insert_err)
                    table_report["status"] = f"ERROR: {str(insert_err)}"
                    report["status"] = "PARTIAL_ERROR"

                report["tables"][table_name] = table_report

    logger.info("Migration complete. Status: %s. Total rows migrated: %d", report["status"], report["total_rows_migrated"])
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate MPP Hub database to Microsoft SQL Server")
    parser.add_argument("--source", type=str, default=None, help="Source database URL (defaults to sqlite:///./mpp_hub.db)")
    parser.add_argument("--target", type=str, default=None, help="Target MS SQL Server database URL (defaults to configured MSSQL in .env)")
    parser.add_argument("--dry-run", action="store_true", help="Perform inspection and count verification without inserting data")
    parser.add_argument("--no-init-schema", action="store_true", help="Skip creating tables on target database")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch insertion chunk size (default: 500)")

    args = parser.parse_args()

    try:
        report = migrate_database(
            source_url=args.source,
            target_url=args.target,
            dry_run=args.dry_run,
            init_schema=not args.no_init_schema,
            batch_size=args.batch_size,
        )
        if report["status"] in ("SUCCESS", "DRY_RUN"):
            print("\nMigration Completed Successfully:")
            for tbl, data in report["tables"].items():
                print(f"  - {tbl:<30}: {data['source_rows']} rows (Status: {data['status']})")
            sys.exit(0)
        else:
            print("\nMigration Finished with Warnings or Errors:", file=sys.stderr)
            for tbl, data in report["tables"].items():
                print(f"  - {tbl:<30}: {data['status']}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        logger.exception("Fatal migration error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
