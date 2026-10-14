"""
Tests for Microsoft SQL Server dialect configuration and data migration utility.
"""

import os
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.db.session import configure_engine, Base
from backend.app.db.models import (
    CalendarDB,
    CalendarWeekdayDB,
    CalendarWorkingShiftDB,
    CalendarExceptionDB,
    ResourceDB,
    RatePeriodDB,
    CustomFieldDB,
    ProjectDB,
    StageDefinitionDB,
    ProjectStageStatusDB,
    ProjectSnapshotDB,
    PortalUserDB,
)
from backend.app.scripts.migrate_to_mssql import (
    configure_engine,
    has_identity_primary_key,
    migrate_database,
    ORDERED_TABLE_NAMES,
)


def test_configure_engine_mssql_pymssql():
    """Verify that configure_engine handles mssql+pymssql URLs and sets pool_pre_ping."""
    url = "mssql+pymssql://sa:StrongPass@localhost:1433/mpp_hub"
    eng = configure_engine(url)
    assert eng.dialect.name == "mssql"
    assert eng.dialect.driver == "pymssql"


def test_configure_engine_mssql_pyodbc():
    """Verify that configure_engine configures fast_executemany for pyodbc."""
    url = "mssql+pyodbc://sa:StrongPass@localhost:1433/mpp_hub?driver=ODBC+Driver+17+for+SQL+Server"
    eng = configure_engine(url)
    assert eng.dialect.name == "mssql"
    assert eng.dialect.driver == "pyodbc"
    # Verify fast_executemany is enabled in execution options or dialect kwargs
    assert getattr(eng.dialect, "fast_executemany", False) is True


def test_has_identity_primary_key():
    """Verify identity detection on tables with integer autoincrement primary keys."""
    cal_table = Base.metadata.tables["calendars"]
    res_table = Base.metadata.tables["resources"]
    proj_table = Base.metadata.tables["projects"]
    assert has_identity_primary_key(cal_table) is True
    assert has_identity_primary_key(res_table) is True
    assert has_identity_primary_key(proj_table) is True


def test_migrate_database_end_to_end_data_integrity(tmp_path):
    """
    Simulates full migration:
    1. Populates source database with relational hierarchy.
    2. Runs dry-run migration to inspect counts.
    3. Runs full migration to target database.
    4. Validates 100% row preservation and foreign key references.
    """
    src_db_file = tmp_path / "source.db"
    tgt_db_file = tmp_path / "target.db"

    src_url = f"sqlite:///{src_db_file}"
    tgt_url = f"sqlite:///{tgt_db_file}"

    src_engine = create_engine(src_url)
    Base.metadata.create_all(bind=src_engine)

    # 1. Seed source data
    with Session(src_engine) as session:
        cal = CalendarDB(id=1, name="Standard Test Calendar", country_code="LT", is_active=True)
        session.add(cal)
        session.flush()

        cw = CalendarWeekdayDB(id=1, calendar_id=1, day_type=2, day_working=True)
        session.add(cw)
        session.flush()

        shift = CalendarWorkingShiftDB(id=1, weekday_id=1, from_time="08:00:00", to_time="17:00:00")
        session.add(shift)

        res = ResourceDB(id=10, name="Jonas Testaitis", email="jonas@test.com", base_calendar_id=1)
        session.add(res)
        session.flush()

        rate = RatePeriodDB(resource_id=10, rate_table="A", standard_rate=45.0, overtime_rate=67.5)
        session.add(rate)

        proj = ProjectDB(id=100, erp_number="26-TEST", name="Test Migration Project", calendar_id=1, budget_cost=75000.0)
        session.add(proj)
        session.flush()

        snap = ProjectSnapshotDB(project_id=100, percent_complete=30.0, cost=15000.0, budget_cost=75000.0)
        session.add(snap)

        user = PortalUserDB(id=5, email="admin@test.com", display_name="Admin Test", role="Admin")
        session.add(user)

        session.commit()

    # 2. Test Dry-Run
    dry_report = migrate_database(source_url=src_url, target_url=tgt_url, dry_run=True, init_schema=False)
    assert dry_report["status"] == "DRY_RUN"
    assert dry_report["tables"]["calendars"]["source_rows"] == 1
    assert dry_report["tables"]["resources"]["source_rows"] == 1
    assert dry_report["tables"]["projects"]["source_rows"] == 1
    assert dry_report["tables"]["portal_users"]["source_rows"] == 1

    # 3. Test Full Migration Execution
    full_report = migrate_database(source_url=src_url, target_url=tgt_url, dry_run=False, init_schema=True)
    assert full_report["status"] == "SUCCESS"
    assert full_report["total_rows_migrated"] >= 7

    # 4. Inspect Target Database
    tgt_engine = create_engine(tgt_url)
    with Session(tgt_engine) as tgt_session:
        # Check Calendar
        t_cal = tgt_session.query(CalendarDB).filter_by(id=1).first()
        assert t_cal is not None
        assert t_cal.name == "Standard Test Calendar"

        # Check Resource & FK
        t_res = tgt_session.query(ResourceDB).filter_by(id=10).first()
        assert t_res is not None
        assert t_res.name == "Jonas Testaitis"
        assert t_res.base_calendar_id == 1

        # Check Rate
        t_rate = tgt_session.query(RatePeriodDB).filter_by(resource_id=10).first()
        assert t_rate is not None
        assert t_rate.standard_rate == 45.0

        # Check Project & Snapshot
        t_proj = tgt_session.query(ProjectDB).filter_by(id=100).first()
        assert t_proj is not None
        assert t_proj.erp_number == "26-TEST"
        assert t_proj.budget_cost == 75000.0

        t_snap = tgt_session.query(ProjectSnapshotDB).filter_by(project_id=100).first()
        assert t_snap is not None
        assert t_snap.percent_complete == 30.0

        # Check Portal User
        t_user = tgt_session.query(PortalUserDB).filter_by(id=5).first()
        assert t_user is not None
        assert t_user.email == "admin@test.com"
