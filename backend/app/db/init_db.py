"""
Database initialization and default data seeding.
Seeds enterprise calendars, resources, and custom fields on fresh start.
"""

from datetime import date
from sqlalchemy.orm import Session

from backend.app.db.models import (
    CalendarDB,
    CalendarExceptionDB,
    CalendarWeekdayDB,
    CalendarWorkingShiftDB,
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


def seed_calendar_weekdays(db: Session, calendar_id: int, schedule_type: str = "standard_40h"):
    """
    Populates 7 weekdays (DayType 1=Sun to 7=Sat) with explicit working shifts.
    """
    if db.query(CalendarWeekdayDB).filter(CalendarWeekdayDB.calendar_id == calendar_id).first():
        return

    if schedule_type == "mon_sun_4h":
        # Monday to Sunday 4 work hours from 13:00 to 17:00
        for day_type in range(1, 8):  # 1=Sun, 2=Mon, ..., 7=Sat
            wd = CalendarWeekdayDB(calendar_id=calendar_id, day_type=day_type, day_working=True)
            db.add(wd)
            db.flush()
            shift = CalendarWorkingShiftDB(weekday_id=wd.id, from_time="13:00:00", to_time="17:00:00")
            db.add(shift)
    else:
        # Standard office 40h: Mon-Fri 08:00-12:00 & 13:00-17:00; Sat-Sun off
        for day_type in range(1, 8):
            is_working = day_type not in (1, 7)  # 1=Sunday, 7=Saturday non-working
            wd = CalendarWeekdayDB(calendar_id=calendar_id, day_type=day_type, day_working=is_working)
            db.add(wd)
            db.flush()
            if is_working:
                s1 = CalendarWorkingShiftDB(weekday_id=wd.id, from_time="08:00:00", to_time="12:00:00")
                s2 = CalendarWorkingShiftDB(weekday_id=wd.id, from_time="13:00:00", to_time="17:00:00")
                db.add(s1)
                db.add(s2)
    db.commit()


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

        # 3. Afternoon shift calendar (Mon-Sun 13:00-17:00, 4h/day)
        cal_afternoon = CalendarDB(
            id=3,
            name="Lithuania – Afternoon 28h (Mon-Sun 13:00-17:00)",
            country_code="LT",
            is_base_calendar=True,
            base_calendar_uid=-1,
        )
        db.add(cal_afternoon)
        db.flush()

        for h in holidays_lt:
            exc = CalendarExceptionDB(
                calendar_id=cal_afternoon.id,
                name=h["name"],
                from_date=h["from_date"],
                to_date=h["to_date"],
                working=False,
                source="IMPORT",
            )
            db.add(exc)

        db.commit()

    # Ensure Calendar 3 exists even if 1 & 2 were already seeded
    cal_3 = db.query(CalendarDB).filter(CalendarDB.id == 3).first()
    if not cal_3:
        cal_3 = CalendarDB(
            id=3,
            name="Lithuania – Afternoon 28h (Mon-Sun 13:00-17:00)",
            country_code="LT",
            is_base_calendar=True,
            base_calendar_uid=-1,
        )
        db.add(cal_3)
        db.flush()
        holidays_lt = fetch_country_holidays("LT", [2026, 2027])
        for h in holidays_lt:
            exc = CalendarExceptionDB(
                calendar_id=cal_3.id,
                name=h["name"],
                from_date=h["from_date"],
                to_date=h["to_date"],
                working=False,
                source="IMPORT",
            )
            db.add(exc)
        db.commit()

    # Ensure all calendars have weekdays populated
    for c in db.query(CalendarDB).all():
        if c.id == 3:
            seed_calendar_weekdays(db, c.id, "mon_sun_4h")
        else:
            seed_calendar_weekdays(db, c.id, "standard_40h")

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

    # 4. Seed Stage Definitions if empty
    from backend.app.db.models import StageDefinitionDB, ProjectDB, ProjectStageStatusDB, ProjectSnapshotDB
    from backend.app.models.enums import StageStatusEnum

    if not db.query(StageDefinitionDB).first():
        stages_data = [
            ("Tabelis", "tabelis", 1),
            ("Sąskaita", "saskaita", 2),
            ("Darbų aktas", "darbu_aktas", 3),
            ("Serviso raportas", "serviso_raportas", 4),
            ("FWQ", "fwq", 5),
            ("Evaluation Form", "evaluation_form", 6),
            ("DSS", "dss", 7),
            ("Admin", "admin", 8),
        ]
        created_stages = []
        for name, code, order in stages_data:
            s_def = StageDefinitionDB(name=name, code=code, sort_order=order, is_active=True)
            db.add(s_def)
            created_stages.append(s_def)
        db.flush()

        # 5. Seed Sample Projects if empty (from screenshot)
        if not db.query(ProjectDB).first():
            sample_projects = [
                {
                    "erp_number": "26-0537",
                    "name": "26-0537 LA MANCHA KNUTSEN - assistance to Burckhardt",
                    "owner": "Domas Krupavičius",
                    "budget_cost": 332459.0,
                    "percent_complete": 86.0,
                    "percent_work_complete": 100.0,
                    "start_date": date(2026, 8, 31),
                    "finish_date": date(2026, 9, 24),
                    "baseline_finish": date(2026, 9, 21),
                    "actual_cost": 24819.0,
                    "cost": 72780.0,
                    "baseline_cost": 6980.0,
                    "baseline_budget": 311305.0,
                    "stages": {
                        "tabelis": StageStatusEnum.DONE,
                        "saskaita": StageStatusEnum.NOT_DONE,
                        "darbu_aktas": StageStatusEnum.DONE,
                        "serviso_raportas": StageStatusEnum.NOT_APPLICABLE,
                        "fwq": StageStatusEnum.NOT_DONE,
                        "evaluation_form": StageStatusEnum.NOT_DONE,
                        "dss": StageStatusEnum.DONE,
                        "admin": StageStatusEnum.NOT_DONE,
                    }
                },
                {
                    "erp_number": "26-0608",
                    "name": "26-0608 AKRISIOS MAN B&W 6G50ME-C9",
                    "owner": "Domas Krupavičius",
                    "budget_cost": 13741.0,
                    "percent_complete": 90.0,
                    "percent_work_complete": 100.0,
                    "start_date": date(2026, 9, 19),
                    "finish_date": date(2026, 9, 30),
                    "baseline_finish": date(2026, 9, 30),
                    "actual_cost": 8264.0,
                    "cost": 8264.0,
                    "baseline_cost": 5700.0,
                    "baseline_budget": 12000.0,
                    "stages": {
                        "tabelis": StageStatusEnum.DONE,
                        "saskaita": StageStatusEnum.NOT_DONE,
                        "darbu_aktas": StageStatusEnum.NOT_DONE,
                        "serviso_raportas": StageStatusEnum.NOT_DONE,
                        "fwq": StageStatusEnum.NOT_DONE,
                        "evaluation_form": StageStatusEnum.NOT_DONE,
                        "dss": StageStatusEnum.NOT_DONE,
                        "admin": StageStatusEnum.NOT_DONE,
                    }
                },
                {
                    "erp_number": "25-0980",
                    "name": "25-0980 Pikasoima IGG katilu apsauga",
                    "owner": "Irma Maslauskaitė Voitkevič",
                    "budget_cost": 1540.0,
                    "percent_complete": 67.0,
                    "percent_work_complete": 100.0,
                    "start_date": date(2023, 11, 6),
                    "finish_date": date(2023, 11, 7),
                    "baseline_finish": date(2025, 11, 12),
                    "actual_cost": 312.0,
                    "cost": 320.4,
                    "baseline_cost": 700.0,
                    "baseline_budget": 640.0,
                    "stages": {
                        "tabelis": StageStatusEnum.NOT_APPLICABLE,
                        "saskaita": StageStatusEnum.DONE,
                        "darbu_aktas": StageStatusEnum.NOT_DONE,
                        "serviso_raportas": StageStatusEnum.NOT_DONE,
                        "fwq": StageStatusEnum.NOT_DONE,
                        "evaluation_form": StageStatusEnum.NOT_DONE,
                        "dss": StageStatusEnum.DONE,
                        "admin": StageStatusEnum.NOT_DONE,
                    }
                },
                {
                    "erp_number": "25-1021",
                    "name": "25-1021 Rubyland Camshaft removal on Yanmar 6EY26 DD",
                    "owner": "Šarūnas Krasauskas",
                    "budget_cost": 202111.0,
                    "percent_complete": 99.0,
                    "percent_work_complete": 100.0,
                    "start_date": date(2026, 9, 27),
                    "finish_date": date(2026, 10, 2),
                    "baseline_finish": date(2026, 9, 19),
                    "actual_cost": 64648.0,
                    "cost": 111440.5,
                    "baseline_cost": 6002.0,
                    "baseline_budget": 10000.0,
                    "stages": {
                        "tabelis": StageStatusEnum.DONE,
                        "saskaita": StageStatusEnum.DONE,
                        "darbu_aktas": StageStatusEnum.NOT_DONE,
                        "serviso_raportas": StageStatusEnum.DONE,
                        "fwq": StageStatusEnum.NOT_DONE,
                        "evaluation_form": StageStatusEnum.NOT_DONE,
                        "dss": StageStatusEnum.DONE,
                        "admin": StageStatusEnum.NOT_DONE,
                    }
                },
                {
                    "erp_number": "26-0183",
                    "name": "26-0183 SEABOARD PIONEER - AE2 WARTSILA 8L20 OVH",
                    "owner": "Vygantas Misevičius",
                    "budget_cost": 77958.0,
                    "percent_complete": 91.0,
                    "percent_work_complete": 100.0,
                    "start_date": date(2026, 8, 17),
                    "finish_date": date(2026, 8, 25),
                    "baseline_finish": date(2026, 9, 5),
                    "actual_cost": 4889.16,
                    "cost": 75391.46,
                    "baseline_cost": 28096.0,
                    "baseline_budget": 61000.0,
                    "stages": {
                        "tabelis": StageStatusEnum.NOT_DONE,
                        "saskaita": StageStatusEnum.DONE,
                        "darbu_aktas": StageStatusEnum.NOT_DONE,
                        "serviso_raportas": StageStatusEnum.NOT_DONE,
                        "fwq": StageStatusEnum.NOT_DONE,
                        "evaluation_form": StageStatusEnum.NOT_DONE,
                        "dss": StageStatusEnum.DONE,
                        "admin": StageStatusEnum.NOT_DONE,
                    }
                }
            ]

            for p_dict in sample_projects:
                stages_map = p_dict.pop("stages")
                pct = p_dict.pop("percent_complete")
                pct_w = p_dict.pop("percent_work_complete")
                f_date = p_dict.pop("finish_date")
                b_finish = p_dict.pop("baseline_finish")
                act_cost = p_dict.pop("actual_cost")
                cost_val = p_dict.pop("cost")
                b_cost = p_dict.pop("baseline_cost")
                b_budg = p_dict.pop("baseline_budget")

                proj = ProjectDB(
                    erp_number=p_dict["erp_number"],
                    name=p_dict["name"],
                    owner=p_dict["owner"],
                    start_date=p_dict["start_date"],
                    budget_cost=p_dict["budget_cost"],
                    calendar_id=1,
                )
                db.add(proj)
                db.flush()

                # Add snapshot
                snap = ProjectSnapshotDB(
                    project_id=proj.id,
                    percent_complete=pct,
                    percent_work_complete=pct_w,
                    start_date=p_dict["start_date"],
                    finish_date=f_date,
                    baseline_finish=b_finish,
                    actual_cost=act_cost,
                    cost=cost_val,
                    baseline_cost=b_cost,
                    baseline_budget=b_budg,
                    budget_cost=p_dict["budget_cost"],
                    source="MANUAL",
                )
                db.add(snap)

                # Add stage statuses
                for s_def in created_stages:
                    st_val = stages_map.get(s_def.code, StageStatusEnum.NOT_DONE)
                    st_status = ProjectStageStatusDB(
                        project_id=proj.id,
                        stage_id=s_def.id,
                        status=st_val,
                        updated_by="system",
                    )
                    db.add(st_status)

        db.commit()
