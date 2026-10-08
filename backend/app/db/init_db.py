"""
Database initialization and default data seeding.
Seeds enterprise calendars, resources, and custom fields on fresh start.
"""

from datetime import date
from sqlalchemy.orm import Session

from backend.app.db.models import (
    CalendarDB,
    CalendarExceptionDB,
    CustomFieldDB,
    RatePeriodDB,
    ResourceDB,
    ResourceFieldValueDB,
)
from backend.app.db.session import Base, engine
from backend.app.models.enums import (
    CustomFieldEntityEnum,
    CustomFieldTypeEnum,
    RateTableEnum,
    ResourceKindEnum,
    ResourceTypeEnum,
)
from backend.app.services.field_ids import get_field_id
from backend.app.services.holiday_service import fetch_country_holidays


def init_db(db: Session) -> None:
    # Create tables
    Base.metadata.create_all(bind=engine)

    # 1. Seed Calendars if empty
    if not db.query(CalendarDB).first():
        cal_lt = CalendarDB(
            id=1,
            name="Lithuania – Standard Enterprise Calendar",
            country_code="LT",
            is_base_calendar=True,
            base_calendar_uid=-1,
        )
        db.add(cal_lt)
        db.flush()

        # Seed holidays for Lithuania
        holidays_lt = fetch_country_holidays("LT", [2026, 2027])
        for h in holidays_lt:
            exc = CalendarExceptionDB(
                calendar_id=cal_lt.id,
                name=h["name"],
                from_date=h["from_date"],
                to_date=h["to_date"],
                working=False,
                source="IMPORT",
            )
            db.add(exc)

        # Norway calendar
        cal_no = CalendarDB(
            id=2,
            name="Norway – Standard Offshore Calendar",
            country_code="NO",
            is_base_calendar=True,
            base_calendar_uid=-1,
        )
        db.add(cal_no)
        db.flush()

        holidays_no = fetch_country_holidays("NO", [2026, 2027])
        for h in holidays_no:
            exc = CalendarExceptionDB(
                calendar_id=cal_no.id,
                name=h["name"],
                from_date=h["from_date"],
                to_date=h["to_date"],
                working=False,
                source="IMPORT",
            )
            db.add(exc)

        db.commit()

    # 2. Seed Custom Fields if empty
    if not db.query(CustomFieldDB).first():
        fid_cc, name_cc = get_field_id(CustomFieldEntityEnum.RESOURCE, CustomFieldTypeEnum.TEXT, 1)
        cf_cost_center = CustomFieldDB(
            field_name="Cost Center",
            entity=CustomFieldEntityEnum.RESOURCE,
            field_type=CustomFieldTypeEnum.TEXT,
            slot_number=1,
            field_id=fid_cc,
            alias="Cost Center",
        )
        db.add(cf_cost_center)

        fid_skill, name_skill = get_field_id(CustomFieldEntityEnum.RESOURCE, CustomFieldTypeEnum.TEXT, 2)
        cf_skill = CustomFieldDB(
            field_name="Skill Level",
            entity=CustomFieldEntityEnum.RESOURCE,
            field_type=CustomFieldTypeEnum.TEXT,
            slot_number=2,
            field_id=fid_skill,
            alias="Skill Level",
        )
        db.add(cf_skill)

        fid_erp, name_erp = get_field_id(CustomFieldEntityEnum.PROJECT, CustomFieldTypeEnum.TEXT, 1)
        cf_erp = CustomFieldDB(
            field_name="ERP Project Number",
            entity=CustomFieldEntityEnum.PROJECT,
            field_type=CustomFieldTypeEnum.TEXT,
            slot_number=1,
            field_id=fid_erp,
            alias="ERP Project Number",
        )
        db.add(cf_erp)
        db.commit()

    # 3. Seed Default Resources if empty
    if not db.query(ResourceDB).first():
        # Resource 1: Tomas Petraitis (Named)
        res1 = ResourceDB(
            id=1,
            guid="d9b56f2e-4b21-4f18-bb92-000000000001",
            ad_upn="tomas.petraitis@enterprise.local",
            name="Tomas Petraitis",
            email="tomas.petraitis@enterprise.com",
            department="Engineering",
            resource_type=ResourceTypeEnum.WORK,
            resource_kind=ResourceKindEnum.NAMED,
            is_generic=False,
            is_active=True,
            base_calendar_id=1,
        )
        db.add(res1)
        db.flush()

        rates_res1 = [
            RatePeriodDB(resource_id=res1.id, rate_table=RateTableEnum.A, standard_rate=45.0, overtime_rate=67.5, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
            RatePeriodDB(resource_id=res1.id, rate_table=RateTableEnum.B, standard_rate=55.0, overtime_rate=82.5, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
            RatePeriodDB(resource_id=res1.id, rate_table=RateTableEnum.C, standard_rate=75.0, overtime_rate=112.5, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
        ]
        db.add_all(rates_res1)

        # Resource 2: Rūta Jonaitė (Named)
        res2 = ResourceDB(
            id=2,
            guid="f7a13c9a-1123-4c91-a182-000000000002",
            ad_upn="ruta.jonaite@enterprise.local",
            name="Rūta Jonaitė",
            email="ruta.jonaite@enterprise.com",
            department="Project Management",
            resource_type=ResourceTypeEnum.WORK,
            resource_kind=ResourceKindEnum.NAMED,
            is_generic=False,
            is_active=True,
            base_calendar_id=1,
        )
        db.add(res2)
        db.flush()

        rates_res2 = [
            RatePeriodDB(resource_id=res2.id, rate_table=RateTableEnum.A, standard_rate=50.0, overtime_rate=75.0, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
            RatePeriodDB(resource_id=res2.id, rate_table=RateTableEnum.B, standard_rate=65.0, overtime_rate=97.5, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
        ]
        db.add_all(rates_res2)

        # Resource 3: Mechanic (Generic placeholder)
        res3 = ResourceDB(
            id=3,
            guid="a1111111-2222-3333-4444-000000000003",
            ad_upn=None,
            name="Mechanic (generic)",
            email=None,
            department="Maintenance",
            resource_type=ResourceTypeEnum.WORK,
            resource_kind=ResourceKindEnum.GENERIC,
            is_generic=True,
            is_active=True,
            base_calendar_id=1,
        )
        db.add(res3)
        db.flush()

        rates_res3 = [
            RatePeriodDB(resource_id=res3.id, rate_table=RateTableEnum.A, standard_rate=40.0, overtime_rate=60.0, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
            RatePeriodDB(resource_id=res3.id, rate_table=RateTableEnum.C, standard_rate=70.0, overtime_rate=105.0, effective_date=date(2026, 1, 1), created_by="finance@enterprise.com"),
        ]
        db.add_all(rates_res3)

        db.commit()
