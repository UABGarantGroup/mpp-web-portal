"""
Database-backed REST API routes for MS Project Centralized Resource & Template Hub.
Enforces RBAC permissions, audit logging, multi-country calendars, and template exports.
"""

from datetime import date
from typing import Any, Dict, List, Optional
import urllib.parse
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.core.auth import CurrentUser, get_current_user, require_roles
from backend.app.db.models import (
    AuditLogDB,
    CalendarDB,
    CalendarExceptionDB,
    CalendarWeekdayDB,
    CalendarWorkingShiftDB,
    CustomFieldDB,
    RatePeriodDB,
    ResourceDB,
    ResourceFieldValueDB,
)
from backend.app.db.session import get_db
from backend.app.models.enums import (
    CustomFieldEntityEnum,
    CustomFieldTypeEnum,
    RateTableEnum,
    ResourceKindEnum,
    ResourceTypeEnum,
)
from backend.app.models.schemas import (
    CalendarCreate,
    CalendarException,
    CalendarModel,
    CalendarWeekdaysUpdate,
    CostRateItem,
    CustomFieldDefinition,
    ProjectTemplateRequest,
    ResourceModel,
    WeekDayModel,
    WorkingShiftModel,
)
from backend.app.services.field_ids import get_field_id
from backend.app.services.holiday_service import fetch_country_holidays, get_supported_countries
from backend.app.services.import_service import validate_and_import_rates, validate_and_import_resources
from backend.app.services.xml_generator import build_ms_project_xml

router = APIRouter()


# --- System Endpoints ---

@router.get("/health", tags=["System"])
def health_check():
    return {"status": "healthy", "service": "mpp-template-engine", "version": "1.0.0"}


# --- Calendars & Holidays Endpoints ---

def map_db_calendar_to_model(c: CalendarDB) -> CalendarModel:
    exceptions = [
        CalendarException(
            name=e.name,
            from_date=e.from_date,
            to_date=e.to_date,
            working=e.working,
        )
        for e in c.exceptions
    ]
    weekdays = [
        WeekDayModel(
            day_type=wd.day_type,
            day_working=wd.day_working,
            working_times=[
                WorkingShiftModel(from_time=shift.from_time, to_time=shift.to_time)
                for shift in wd.working_times
            ],
        )
        for wd in c.weekdays
    ]
    return CalendarModel(
        id=c.id,
        name=c.name,
        country_code=c.country_code,
        is_base_calendar=c.is_base_calendar,
        base_calendar_uid=c.base_calendar_uid,
        weekdays=weekdays,
        exceptions=exceptions,
    )


@router.get("/api/calendars", response_model=List[CalendarModel], tags=["Calendars"])
def list_calendars(db: Session = Depends(get_db)):
    cal_dbs = db.query(CalendarDB).all()
    return [map_db_calendar_to_model(c) for c in cal_dbs]


@router.get("/api/calendars/countries", tags=["Calendars"])
def get_countries():
    return get_supported_countries()


@router.get("/api/calendars/{calendar_id}", response_model=CalendarModel, tags=["Calendars"])
def get_calendar(calendar_id: int, db: Session = Depends(get_db)):
    cal = db.query(CalendarDB).filter(CalendarDB.id == calendar_id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="Calendar not found")
    return map_db_calendar_to_model(cal)


@router.post("/api/calendars", response_model=CalendarModel, status_code=status.HTTP_201_CREATED, tags=["Calendars"])
def create_calendar(
    cal_in: CalendarCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    new_cal = CalendarDB(
        name=cal_in.name,
        country_code=cal_in.country_code,
        is_base_calendar=True,
        base_calendar_uid=-1,
    )
    db.add(new_cal)
    db.flush()

    if cal_in.weekdays:
        for wd in cal_in.weekdays:
            wd_db = CalendarWeekdayDB(
                calendar_id=new_cal.id,
                day_type=wd.day_type,
                day_working=wd.day_working,
            )
            db.add(wd_db)
            db.flush()
            if wd.day_working and wd.working_times:
                for shift in wd.working_times:
                    s_db = CalendarWorkingShiftDB(
                        weekday_id=wd_db.id,
                        from_time=shift.from_time,
                        to_time=shift.to_time,
                    )
                    db.add(s_db)
    else:
        # Default standard 40h office
        for day_type in range(1, 8):
            is_working = day_type not in (1, 7)
            wd_db = CalendarWeekdayDB(calendar_id=new_cal.id, day_type=day_type, day_working=is_working)
            db.add(wd_db)
            db.flush()
            if is_working:
                db.add(CalendarWorkingShiftDB(weekday_id=wd_db.id, from_time="08:00:00", to_time="12:00:00"))
                db.add(CalendarWorkingShiftDB(weekday_id=wd_db.id, from_time="13:00:00", to_time="17:00:00"))

    # Also auto-import holidays for country_code
    try:
        holidays_imported = fetch_country_holidays(new_cal.country_code, [date.today().year, date.today().year + 1])
        for h in holidays_imported:
            exc = CalendarExceptionDB(
                calendar_id=new_cal.id,
                name=h["name"],
                from_date=h["from_date"],
                to_date=h["to_date"],
                working=False,
                source="IMPORT",
            )
            db.add(exc)
    except Exception:
        pass

    db.commit()
    db.refresh(new_cal)
    return map_db_calendar_to_model(new_cal)


@router.put("/api/calendars/{calendar_id}/weekdays", response_model=CalendarModel, tags=["Calendars"])
def update_calendar_weekdays(
    calendar_id: int,
    weekdays_in: CalendarWeekdaysUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    cal = db.query(CalendarDB).filter(CalendarDB.id == calendar_id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="Calendar not found")

    # Clear existing weekdays for this calendar
    existing_wds = db.query(CalendarWeekdayDB).filter(CalendarWeekdayDB.calendar_id == calendar_id).all()
    for wd in existing_wds:
        db.delete(wd)
    db.flush()

    for wd in weekdays_in.weekdays:
        wd_db = CalendarWeekdayDB(
            calendar_id=calendar_id,
            day_type=wd.day_type,
            day_working=wd.day_working,
        )
        db.add(wd_db)
        db.flush()
        if wd.day_working and wd.working_times:
            for shift in wd.working_times:
                s_db = CalendarWorkingShiftDB(
                    weekday_id=wd_db.id,
                    from_time=shift.from_time,
                    to_time=shift.to_time,
                )
                db.add(s_db)

    db.commit()
    db.refresh(cal)
    return map_db_calendar_to_model(cal)


@router.post("/api/calendars/{calendar_id}/import-holidays", response_model=CalendarModel, tags=["Calendars"])
def import_holidays(
    calendar_id: int,
    years: Optional[List[int]] = Query(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    cal = db.query(CalendarDB).filter(CalendarDB.id == calendar_id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="Calendar not found")

    imported = fetch_country_holidays(cal.country_code, years)
    for h in imported:
        exists = db.query(CalendarExceptionDB).filter(
            CalendarExceptionDB.calendar_id == cal.id,
            CalendarExceptionDB.from_date == h["from_date"],
            CalendarExceptionDB.name == h["name"],
        ).first()
        if not exists:
            exc = CalendarExceptionDB(
                calendar_id=cal.id,
                name=h["name"],
                from_date=h["from_date"],
                to_date=h["to_date"],
                working=False,
                source="IMPORT",
            )
            db.add(exc)
    db.commit()
    db.refresh(cal)

    return map_db_calendar_to_model(cal)


# --- Resources Endpoints ---

@router.get("/api/resources", response_model=List[ResourceModel], tags=["Resources"])
def list_resources(
    department: Optional[str] = Query(None),
    kind: Optional[ResourceKindEnum] = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(ResourceDB)
    if not include_inactive:
        query = query.filter(ResourceDB.is_active == True)
    if department:
        query = query.filter(ResourceDB.department.ilike(department))
    if kind:
        query = query.filter(ResourceDB.resource_kind == kind)

    res_dbs = query.all()
    results = []
    for r in res_dbs:
        rates = [
            CostRateItem(
                rate_table=rp.rate_table,
                standard_rate=rp.standard_rate,
                overtime_rate=rp.overtime_rate,
                cost_per_use=rp.cost_per_use,
                effective_date=rp.effective_date,
                rates_to=rp.rates_to,
            )
            for rp in r.rates
        ]
        cf_vals = {fv.custom_field.alias or fv.custom_field.field_name: fv.value for fv in r.field_values if fv.custom_field}

        results.append(
            ResourceModel(
                id=r.id,
                guid=r.guid,
                ad_upn=r.ad_upn,
                name=r.name,
                email=r.email,
                department=r.department,
                resource_type=r.resource_type,
                resource_kind=r.resource_kind,
                is_generic=r.is_generic,
                is_active=r.is_active,
                base_calendar_id=r.base_calendar_id,
                rates=rates,
                custom_field_values=cf_vals,
            )
        )
    return results


@router.post("/api/resources", response_model=ResourceModel, status_code=status.HTTP_201_CREATED, tags=["Resources"])
def create_resource(
    resource: ResourceModel,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    # If generic, only Admin is allowed
    if resource.resource_kind == ResourceKindEnum.GENERIC and not user.has_any_role(["Admin"]):
        raise HTTPException(status_code=403, detail="Only Admins can create generic resources.")

    new_res = ResourceDB(
        name=resource.name,
        email=resource.email,
        department=resource.department,
        ad_upn=resource.ad_upn,
        resource_type=resource.resource_type,
        resource_kind=resource.resource_kind,
        is_generic=resource.is_generic,
        is_active=resource.is_active,
        base_calendar_id=resource.base_calendar_id,
    )
    if resource.guid:
        new_res.guid = resource.guid
    db.add(new_res)
    db.commit()
    db.refresh(new_res)

    resource.id = new_res.id
    return resource


@router.delete("/api/resources/{resource_id}", response_model=ResourceModel, tags=["Resources"])
def soft_delete_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    res = db.query(ResourceDB).filter(ResourceDB.id == resource_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Soft delete: sets is_active = False
    res.is_active = False

    # Audit log
    audit = AuditLogDB(
        entity_type="RESOURCE",
        entity_id=str(resource_id),
        action="SOFT_DELETE",
        changed_by=user.email,
        details=f"Resource '{res.name}' deactivated by {user.email}",
    )
    db.add(audit)
    db.commit()

    return ResourceModel(
        id=res.id,
        guid=res.guid,
        name=res.name,
        email=res.email,
        department=res.department,
        resource_type=res.resource_type,
        resource_kind=res.resource_kind,
        is_generic=res.is_generic,
        is_active=res.is_active,
        base_calendar_id=res.base_calendar_id,
        rates=[],
        custom_field_values={},
    )


# --- Cost Rates Endpoints (Finance Manager Role) ---

@router.put("/api/resources/{resource_id}/rates", response_model=List[CostRateItem], tags=["Cost Rates"])
def update_resource_rates(
    resource_id: int,
    rates: List[CostRateItem],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["FinanceManager", "Admin"])),
):
    res = db.query(ResourceDB).filter(ResourceDB.id == resource_id).first()
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Clear previous active rates or add historical entries
    db.query(RatePeriodDB).filter(RatePeriodDB.resource_id == resource_id).delete()

    created_rates = []
    for r in rates:
        rp = RatePeriodDB(
            resource_id=resource_id,
            rate_table=r.rate_table,
            standard_rate=r.standard_rate,
            overtime_rate=r.overtime_rate,
            cost_per_use=r.cost_per_use,
            effective_date=r.effective_date or date.today(),
            rates_to=r.rates_to,
            created_by=user.email,
        )
        db.add(rp)
        created_rates.append(r)

    # Audit log
    audit = AuditLogDB(
        entity_type="RATE",
        entity_id=str(resource_id),
        action="UPDATE",
        changed_by=user.email,
        details=f"Rates updated for resource '{res.name}' with {len(rates)} tables by {user.email}",
    )
    db.add(audit)
    db.commit()

    return created_rates


# --- Custom Fields Endpoints ---

@router.get("/api/custom-fields", tags=["Custom Fields"])
def list_custom_fields(db: Session = Depends(get_db)):
    cfs = db.query(CustomFieldDB).all()
    return [
        {
            "id": cf.id,
            "field_name": cf.field_name,
            "entity": cf.entity,
            "field_type": cf.field_type,
            "slot_number": cf.slot_number,
            "field_id": cf.field_id,
            "alias": cf.alias,
            "default_value": cf.default_value,
            "lookups": [lv.value for lv in cf.lookup_values],
        }
        for cf in cfs
    ]


@router.post("/api/custom-fields", status_code=status.HTTP_201_CREATED, tags=["Custom Fields"])
def create_custom_field(
    field_name: str,
    entity: CustomFieldEntityEnum = CustomFieldEntityEnum.RESOURCE,
    field_type: CustomFieldTypeEnum = CustomFieldTypeEnum.TEXT,
    slot_number: int = 1,
    alias: Optional[str] = None,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    fid, internal_name = get_field_id(entity, field_type, slot_number)
    cf = CustomFieldDB(
        field_name=field_name,
        entity=entity,
        field_type=field_type,
        slot_number=slot_number,
        field_id=fid,
        alias=alias or field_name,
    )
    db.add(cf)
    db.commit()
    db.refresh(cf)
    return cf


# --- CSV / Excel Import Endpoints ---

@router.post("/api/import/resources", tags=["Import"])
async def import_resources_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Query(True, description="When true, only validates and previews without saving"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    content = await file.read()
    try:
        result = validate_and_import_resources(db, content, file.filename, dry_run=dry_run)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/import/rates", tags=["Import"])
async def import_rates_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Query(True, description="When true, only validates and previews without saving"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["FinanceManager", "Admin"])),
):
    content = await file.read()
    try:
        result = validate_and_import_rates(db, content, file.filename, created_by=user.email, dry_run=dry_run)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Template Export Endpoints ---

@router.post("/api/templates/export/xml", tags=["Export"])
def export_project_xml(template_req: ProjectTemplateRequest, db: Session = Depends(get_db)):
    # Build dictionary of calendars
    cal_dbs = db.query(CalendarDB).all()
    calendars_dict = {c.id: map_db_calendar_to_model(c) for c in cal_dbs}

    # Build dictionary of resources
    res_dbs = db.query(ResourceDB).all()
    resources_dict = {
        r.id: ResourceModel(
            id=r.id,
            guid=r.guid,
            ad_upn=r.ad_upn,
            name=r.name,
            email=r.email,
            department=r.department,
            resource_type=r.resource_type,
            resource_kind=r.resource_kind,
            is_generic=r.is_generic,
            is_active=r.is_active,
            base_calendar_id=r.base_calendar_id,
            rates=[
                CostRateItem(
                    rate_table=rp.rate_table,
                    standard_rate=rp.standard_rate,
                    overtime_rate=rp.overtime_rate,
                    cost_per_use=rp.cost_per_use,
                    effective_date=rp.effective_date,
                    rates_to=rp.rates_to,
                )
                for rp in r.rates
            ],
            custom_field_values={
                fv.custom_field.alias or fv.custom_field.field_name: fv.value
                for fv in r.field_values if fv.custom_field
            },
        )
        for r in res_dbs
    }

    xml_content = build_ms_project_xml(
        template_req=template_req,
        calendars=calendars_dict,
        resources=resources_dict,
    )

    clean_title = "".join(c for c in template_req.project_title if c.isalnum() or c in ("-", "_", " ")).strip()
    ascii_filename = f"{clean_title.replace(' ', '_').lower()}_template.xml"
    quoted_filename = urllib.parse.quote(f"{template_req.project_title}_template.xml")

    return Response(
        content=xml_content,
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quoted_filename}"
        },
    )


# --- Project Management & Wizard Endpoints (Phase 2) ---

from backend.app.db.models import (
    ProjectDB,
    ProjectTeamResourceDB,
    StageDefinitionDB,
    ProjectStageStatusDB,
    ProjectSnapshotDB,
)
from backend.app.models.schemas import (
    ProjectCreate,
    ProjectBudgetUpdate,
    StageDefinitionSchema,
    StageDefinitionCreate,
    StageStatusUpdate,
    ProjectSnapshotCreate,
    StageStatusEnum,
)


@router.get("/api/projects", tags=["Projects"])
def list_projects(
    owner: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(ProjectDB)
    if owner:
        query = query.filter(ProjectDB.owner.ilike(f"%{owner}%"))
    if search:
        query = query.filter(
            (ProjectDB.name.ilike(f"%{search}%")) | (ProjectDB.erp_number.ilike(f"%{search}%"))
        )
    projects = query.all()
    results = []
    for p in projects:
        results.append({
            "id": p.id,
            "project_guid": p.project_guid,
            "erp_number": p.erp_number,
            "name": p.name,
            "owner": p.owner,
            "start_date": p.start_date,
            "calendar_id": p.calendar_id,
            "budget_cost": p.budget_cost,
            "created_at": p.created_at,
            "team_resource_ids": [tm.resource_id for tm in p.team_members],
        })
    return results


@router.post("/api/projects", status_code=status.HTTP_201_CREATED, tags=["Projects"])
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["PM", "Admin"])),
):
    # Check if ERP number exists
    existing = db.query(ProjectDB).filter(ProjectDB.erp_number == project_in.erp_number).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Project with ERP number '{project_in.erp_number}' already exists.")

    new_project = ProjectDB(
        erp_number=project_in.erp_number,
        name=project_in.name,
        owner=project_in.owner,
        calendar_id=project_in.calendar_id,
        start_date=project_in.start_date,
        budget_cost=project_in.budget_cost or 0.0,
    )
    db.add(new_project)
    db.flush()

    # Link team members
    for r_id in project_in.team_resource_ids:
        tm = ProjectTeamResourceDB(project_id=new_project.id, resource_id=r_id)
        db.add(tm)

    # Initialize stage statuses from active stage definitions
    active_stages = db.query(StageDefinitionDB).filter(StageDefinitionDB.is_active == True).all()
    for s_def in active_stages:
        st_status = ProjectStageStatusDB(
            project_id=new_project.id,
            stage_id=s_def.id,
            status=StageStatusEnum.NOT_DONE,
            updated_by=user.email,
        )
        db.add(st_status)

    # Initial snapshot
    init_snap = ProjectSnapshotDB(
        project_id=new_project.id,
        percent_complete=0.0,
        percent_work_complete=0.0,
        start_date=project_in.start_date,
        budget_cost=new_project.budget_cost,
        source="MANUAL",
    )
    db.add(init_snap)

    # Audit log
    audit = AuditLogDB(
        entity_type="PROJECT",
        entity_id=str(new_project.id),
        action="CREATE",
        changed_by=user.email,
        details=f"Project '{new_project.name}' created by {user.email}",
    )
    db.add(audit)
    db.commit()
    db.refresh(new_project)

    return {
        "id": new_project.id,
        "project_guid": new_project.project_guid,
        "erp_number": new_project.erp_number,
        "name": new_project.name,
        "owner": new_project.owner,
        "budget_cost": new_project.budget_cost,
        "team_resource_ids": project_in.team_resource_ids,
        "stage_statuses": [
            {"stage_id": ss.stage_id, "status": ss.status.value} for ss in new_project.stage_statuses
        ],
    }


@router.get("/api/projects/{project_id}", tags=["Projects"])
def get_project_details(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(ProjectDB).filter(ProjectDB.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    stages_dict = {
        ss.stage_definition.code: {
            "stage_id": ss.stage_id,
            "name": ss.stage_definition.name,
            "status": ss.status,
            "updated_by": ss.updated_by,
            "updated_at": ss.updated_at,
        }
        for ss in proj.stage_statuses if ss.stage_definition
    }

    latest_snapshot = proj.snapshots[0] if proj.snapshots else None

    return {
        "id": proj.id,
        "project_guid": proj.project_guid,
        "erp_number": proj.erp_number,
        "name": proj.name,
        "owner": proj.owner,
        "start_date": proj.start_date,
        "calendar_id": proj.calendar_id,
        "budget_cost": proj.budget_cost,
        "team_members": [
            {
                "id": tm.resource.id,
                "name": tm.resource.name,
                "resource_kind": tm.resource.resource_kind,
                "is_generic": tm.resource.is_generic,
            }
            for tm in proj.team_members if tm.resource
        ],
        "stages": stages_dict,
        "metrics": {
            "percent_complete": latest_snapshot.percent_complete if latest_snapshot else 0.0,
            "percent_work_complete": latest_snapshot.percent_work_complete if latest_snapshot else 0.0,
            "start_date": latest_snapshot.start_date if latest_snapshot else proj.start_date,
            "finish_date": latest_snapshot.finish_date if latest_snapshot else None,
            "baseline_finish": latest_snapshot.baseline_finish if latest_snapshot else None,
            "actual_cost": latest_snapshot.actual_cost if latest_snapshot else 0.0,
            "cost": latest_snapshot.cost if latest_snapshot else 0.0,
            "baseline_cost": latest_snapshot.baseline_cost if latest_snapshot else 0.0,
            "baseline_budget": latest_snapshot.baseline_budget if latest_snapshot else 0.0,
            "budget_cost": latest_snapshot.budget_cost if latest_snapshot else proj.budget_cost,
        }
    }


@router.put("/api/projects/{project_id}/budget", tags=["Projects"])
def update_project_budget(
    project_id: int,
    budget_in: ProjectBudgetUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["FinanceManager", "Admin"])),
):
    proj = db.query(ProjectDB).filter(ProjectDB.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    old_budget = proj.budget_cost
    proj.budget_cost = budget_in.budget_cost

    # Update latest snapshot budget cost too
    if proj.snapshots:
        proj.snapshots[0].budget_cost = budget_in.budget_cost

    audit = AuditLogDB(
        entity_type="BUDGET",
        entity_id=str(project_id),
        action="UPDATE",
        changed_by=user.email,
        details=f"Budget updated from {old_budget} to {budget_in.budget_cost} by {user.email}",
    )
    db.add(audit)
    db.commit()

    return {"project_id": proj.id, "budget_cost": proj.budget_cost, "updated_by": user.email}


@router.post("/api/projects/{project_id}/template/xml", tags=["Projects"])
def export_project_template_by_id(project_id: int, db: Session = Depends(get_db)):
    proj = db.query(ProjectDB).filter(ProjectDB.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    team_ids = [tm.resource_id for tm in proj.team_members]
    if not team_ids:
        # Default to all active resources if none explicitly attached
        team_ids = [r.id for r in db.query(ResourceDB).filter(ResourceDB.is_active == True).all()]

    template_req = ProjectTemplateRequest(
        project_id=proj.id,
        project_guid=proj.project_guid,
        project_erp_number=proj.erp_number,
        project_title=proj.name,
        company_name="Enterprise Global",
        start_date=proj.start_date or date.today(),
        calendar_id=proj.calendar_id,
        selected_resource_ids=team_ids,
        budget_cost=proj.budget_cost,
        custom_fields=[
            CustomFieldDefinition(field_name="ERP Project Number", entity=CustomFieldEntityEnum.PROJECT, slot_number=1, alias="ERP Project Number"),
            CustomFieldDefinition(field_name="Cost Center", entity=CustomFieldEntityEnum.RESOURCE, slot_number=1, alias="Cost Center"),
        ],
        project_custom_values={"ERP Project Number": proj.erp_number},
    )

    return export_project_xml(template_req, db=db)


# --- Stage Definitions & Status Toggles (Phase 3) ---

@router.get("/api/stages", tags=["Stages"])
def list_stages(include_blocked: bool = Query(False), db: Session = Depends(get_db)):
    query = db.query(StageDefinitionDB).order_by(StageDefinitionDB.sort_order)
    if not include_blocked:
        query = query.filter(StageDefinitionDB.is_active == True)
    return query.all()


@router.post("/api/stages", status_code=status.HTTP_201_CREATED, tags=["Stages"])
def create_stage(
    stage_in: StageDefinitionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    existing = db.query(StageDefinitionDB).filter(StageDefinitionDB.code == stage_in.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Stage code already exists")

    new_stage = StageDefinitionDB(
        name=stage_in.name,
        code=stage_in.code,
        sort_order=stage_in.sort_order,
        is_active=True,
    )
    db.add(new_stage)
    db.commit()
    db.refresh(new_stage)

    # Add default NOT_DONE status for all existing projects
    all_projects = db.query(ProjectDB).all()
    for p in all_projects:
        st_status = ProjectStageStatusDB(
            project_id=p.id,
            stage_id=new_stage.id,
            status=StageStatusEnum.NOT_DONE,
            updated_by="system",
        )
        db.add(st_status)
    db.commit()

    return new_stage


@router.put("/api/stages/{stage_id}/block", tags=["Stages"])
def toggle_stage_blocked(
    stage_id: int,
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    stage = db.query(StageDefinitionDB).filter(StageDefinitionDB.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    if is_active is not None:
        stage.is_active = is_active
    else:
        stage.is_active = not stage.is_active
    db.commit()
    return {"id": stage.id, "name": stage.name, "is_active": stage.is_active}


@router.put("/api/projects/{project_id}/stages/{stage_id}", tags=["Stages"])
def update_project_stage_status(
    project_id: int,
    stage_id: int,
    status_in: StageStatusUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["PM", "FinanceManager", "Admin"])),
):
    proj = db.query(ProjectDB).filter(ProjectDB.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    stage_def = db.query(StageDefinitionDB).filter(StageDefinitionDB.id == stage_id).first()
    if not stage_def:
        raise HTTPException(status_code=404, detail="Stage not found")
    if not stage_def.is_active:
        raise HTTPException(status_code=400, detail="This stage is blocked by Admin and cannot be modified.")

    # If PM, can only update own projects unless Admin or FinanceManager
    if "PM" in user.roles and not user.has_any_role(["Admin", "FinanceManager"]):
        is_owner = False
        if not proj.owner:
            is_owner = True
        else:
            owner_lower = proj.owner.lower()
            tokens = [user.email.lower(), user.username.lower()]
            if "@" in user.email:
                tokens.append(user.email.split("@")[0].lower())
            for t in tokens:
                if t in owner_lower or owner_lower in t:
                    is_owner = True
                    break
        if not is_owner:
            raise HTTPException(status_code=403, detail="You can only update stages for your own projects.")

    st_status = db.query(ProjectStageStatusDB).filter(
        ProjectStageStatusDB.project_id == project_id,
        ProjectStageStatusDB.stage_id == stage_id,
    ).first()

    if not st_status:
        st_status = ProjectStageStatusDB(
            project_id=project_id,
            stage_id=stage_id,
            status=status_in.status,
            updated_by=user.email,
        )
        db.add(st_status)
    else:
        st_status.status = status_in.status
        st_status.updated_by = user.email

    audit = AuditLogDB(
        entity_type="STAGE",
        entity_id=f"{project_id}_{stage_id}",
        action="UPDATE",
        changed_by=user.email,
        details=f"Stage {stage_id} set to {status_in.status.value} for project {proj.erp_number}",
    )
    db.add(audit)
    db.commit()

    return {
        "project_id": project_id,
        "stage_id": stage_id,
        "status": st_status.status,
        "updated_by": user.email,
    }


# --- Portfolio View Aggregation (Phase 3) ---

@router.get("/api/portfolio", tags=["Portfolio"])
def get_portfolio_view(db: Session = Depends(get_db)):
    """
    Returns enterprise project center view grouped by Owner (PM).
    Matches the exact layout of the MS Project Online portfolio center.
    """
    active_stages = db.query(StageDefinitionDB).filter(StageDefinitionDB.is_active == True).order_by(StageDefinitionDB.sort_order).all()
    stage_columns = [{"id": s.id, "name": s.name, "code": s.code} for s in active_stages]

    projects = db.query(ProjectDB).all()

    # Group projects by Owner
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for p in projects:
        owner = p.owner or "Unassigned"
        snap = p.snapshots[0] if p.snapshots else None

        # Collect stage status values
        stages_map = {}
        for ss in p.stage_statuses:
            if ss.stage_definition and ss.stage_definition.is_active:
                stages_map[ss.stage_definition.code] = ss.status.value

        p_data = {
            "id": p.id,
            "project_guid": p.project_guid,
            "erp_number": p.erp_number,
            "name": p.name,
            "owner": p.owner,
            "percent_complete": snap.percent_complete if snap else 0.0,
            "percent_work_complete": snap.percent_work_complete if snap else 0.0,
            "start_date": snap.start_date.isoformat() if (snap and snap.start_date) else (p.start_date.isoformat() if p.start_date else None),
            "finish_date": snap.finish_date.isoformat() if (snap and snap.finish_date) else None,
            "baseline_finish": snap.baseline_finish.isoformat() if (snap and snap.baseline_finish) else None,
            "actual_cost": snap.actual_cost if snap else 0.0,
            "cost": snap.cost if snap else 0.0,
            "baseline_cost": snap.baseline_cost if snap else 0.0,
            "baseline_budget": snap.baseline_budget if snap else 0.0,
            "budget_cost": snap.budget_cost if snap else p.budget_cost,
            "stages": stages_map,
        }

        if owner not in grouped:
            grouped[owner] = []
        grouped[owner].append(p_data)

    # Compute group summaries (yellow summary rows from Project Center)
    portfolio_groups = []
    for owner, p_list in sorted(grouped.items()):
        total_actual_cost = sum(p["actual_cost"] for p in p_list)
        total_cost = sum(p["cost"] for p in p_list)
        total_baseline_cost = sum(p["baseline_cost"] for p in p_list)
        total_baseline_budget = sum(p["baseline_budget"] for p in p_list)
        total_budget_cost = sum(p["budget_cost"] for p in p_list)

        starts = [p["start_date"] for p in p_list if p["start_date"]]
        finishes = [p["finish_date"] for p in p_list if p["finish_date"]]
        earliest_start = min(starts) if starts else None
        latest_finish = max(finishes) if finishes else None

        portfolio_groups.append({
            "owner": owner,
            "project_count": len(p_list),
            "summary": {
                "start_date": earliest_start,
                "finish_date": latest_finish,
                "total_actual_cost": total_actual_cost,
                "total_cost": total_cost,
                "total_baseline_cost": total_baseline_cost,
                "total_baseline_budget": total_baseline_budget,
                "total_budget_cost": total_budget_cost,
            },
            "projects": p_list,
        })

    return {
        "stage_columns": stage_columns,
        "groups": portfolio_groups,
    }

