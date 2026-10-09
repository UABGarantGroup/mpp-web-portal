"""
Database-backed REST API routes for MS Project Centralized Resource & Template Hub.
Enforces RBAC permissions, audit logging, multi-country calendars, and template exports.
"""

import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional
import urllib.parse
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from backend.app.core.auth import CurrentUser, get_current_user, require_roles
from backend.app.core.config import settings
from backend.app.db.models import (
    AuditLogDB,
    CalendarDB,
    CalendarExceptionDB,
    CalendarWeekdayDB,
    CalendarWorkingShiftDB,
    CustomFieldDB,
    PortalUserDB,
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
    CalendarUpdate,
    CalendarWeekdaysUpdate,
    CostRateItem,
    CustomFieldDefinition,
    EntraConfigUpdate,
    EntraGroupSchema,
    EntraStatusResponse,
    EntraUserSchema,
    GroupImportRequest,
    GroupImportResult,
    PortalUserCreate,
    PortalUserModel,
    PortalUserUpdate,
    ProjectTemplateRequest,
    ResourceAddByEmailRequest,
    ResourceModel,
    WeekDayModel,
    WorkingShiftModel,
)
from backend.app.services.entra_graph import entra_graph_service
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
        is_active=c.is_active,
        weekdays=weekdays,
        exceptions=exceptions,
    )


@router.get("/api/calendars", response_model=List[CalendarModel], tags=["Calendars"])
def list_calendars(include_inactive: bool = Query(False), db: Session = Depends(get_db)):
    query = db.query(CalendarDB)
    if not include_inactive:
        query = query.filter(CalendarDB.is_active == True)
    cal_dbs = query.all()
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


@router.put("/api/calendars/{calendar_id}", response_model=CalendarModel, tags=["Calendars"])
def update_calendar(
    calendar_id: int,
    cal_update: CalendarUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    cal = db.query(CalendarDB).filter(CalendarDB.id == calendar_id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="Calendar not found")

    if cal_update.name is not None and cal_update.name.strip():
        cal.name = cal_update.name.strip()
    if cal_update.country_code is not None and cal_update.country_code.strip():
        cal.country_code = cal_update.country_code.strip()
    if cal_update.is_active is not None:
        cal.is_active = cal_update.is_active

    db.commit()
    db.refresh(cal)
    return map_db_calendar_to_model(cal)


@router.put("/api/calendars/{calendar_id}/hide", response_model=CalendarModel, tags=["Calendars"])
def toggle_hide_calendar(
    calendar_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    cal = db.query(CalendarDB).filter(CalendarDB.id == calendar_id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="Calendar not found")

    cal.is_active = not cal.is_active
    db.commit()
    db.refresh(cal)
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
        is_active=cal_in.is_active if cal_in.is_active is not None else True,
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
    ResourceSwapItem,
    ProjectRefreshRequest,
)
from backend.app.services.mpxj_parser import parse_project_file


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


@router.get("/api/projects/{project_id}/template/xml", tags=["Projects"])
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
            "last_updated_by": p.last_updated_by or (snap.source if snap else None),
            "last_updated_at": p.last_updated_at.strftime("%Y-%m-%d %H:%M") if p.last_updated_at else (snap.recorded_at.strftime("%Y-%m-%d %H:%M") if snap else None),
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


# --- Project Schedule Upload & Refresh Endpoints (Phase 4) ---

@router.post("/api/projects/{project_id}/upload-schedule", tags=["Projects"])
async def upload_project_schedule(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["PM", "Admin"])),
):
    proj = db.query(ProjectDB).filter(ProjectDB.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        parsed = parse_project_file(content, file.filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse project file: {str(e)}")

    # Safety check: Verify the file belongs to this project to avoid uploading to the wrong row
    file_erp = parsed.get("erp_number")
    file_title = parsed.get("title")
    target_erp = proj.erp_number.strip().lower()

    if file_erp:
        if file_erp.strip().lower() != target_erp:
            raise HTTPException(
                status_code=400,
                detail=f"Project mismatch! File contains ERP '{file_erp}', but target row is '{proj.erp_number}' ({proj.name}). Upload rejected to prevent overwriting wrong project."
            )
    elif file_title and target_erp:
        # Check if ERP number appears anywhere in the file title or project properties
        clean_title = file_title.lower()
        if target_erp not in clean_title and target_erp.replace("-", "") not in clean_title.replace("-", ""):
            # Also check if filename has the ERP number
            clean_fn = file.filename.lower()
            if target_erp not in clean_fn and target_erp.replace("-", "") not in clean_fn.replace("-", ""):
                # If neither the file properties nor the filename match the project ERP, warn and block
                raise HTTPException(
                    status_code=400,
                    detail=f"Project verification error! Neither the file title ('{file_title}') nor filename ('{file.filename}') matches target ERP number '{proj.erp_number}'. Please check that you selected the schedule for this project."
                )

    # Update latest project snapshot or create new one
    now = datetime.utcnow()
    snapshot = ProjectSnapshotDB(
        project_id=proj.id,
        percent_complete=parsed["percent_complete"],
        percent_work_complete=parsed["percent_work_complete"],
        start_date=parsed["start_date"] or proj.start_date,
        finish_date=parsed["finish_date"],
        baseline_finish=parsed["baseline_finish"],
        actual_cost=parsed["actual_cost"],
        cost=parsed["cost"],
        baseline_cost=parsed["baseline_cost"],
        baseline_budget=parsed["baseline_budget"],
        budget_cost=proj.budget_cost,
        source="UPLOAD",
        recorded_at=now,
    )
    db.add(snapshot)

    # Update project last_updated_by and last_updated_at
    proj.last_updated_by = user.email
    proj.last_updated_at = now

    # Detect generic resources in the uploaded file for the replacement wizard
    file_resources = parsed.get("resources", [])
    generic_found = [r for r in file_resources if r.get("is_generic")]

    audit = AuditLogDB(
        entity_type="PROJECT_SCHEDULE",
        entity_id=str(proj.id),
        action="UPLOAD",
        changed_by=user.email,
        details=f"Schedule file '{file.filename}' uploaded by {user.email}. % Complete: {parsed['percent_complete']}%, Cost: €{parsed['cost']}",
    )
    db.add(audit)
    db.commit()

    return {
        "message": f"Schedule parsed and portfolio snapshot updated from '{file.filename}'",
        "project_id": proj.id,
        "project_name": proj.name,
        "erp_number": proj.erp_number,
        "metrics": {
            "percent_complete": parsed["percent_complete"],
            "percent_work_complete": parsed["percent_work_complete"],
            "start_date": parsed["start_date"],
            "finish_date": parsed["finish_date"],
            "baseline_finish": parsed["baseline_finish"],
            "actual_cost": parsed["actual_cost"],
            "cost": parsed["cost"],
            "baseline_cost": parsed["baseline_cost"],
            "baseline_budget": parsed["baseline_budget"],
            "budget_cost": proj.budget_cost,
        },
        "file_resources": file_resources,
        "generic_resources_to_replace": generic_found,
    }


@router.post("/api/projects/{project_id}/refresh", tags=["Projects"])
def refresh_project_template(
    project_id: int,
    refresh_req: ProjectRefreshRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["PM", "Admin"])),
):
    proj = db.query(ProjectDB).filter(ProjectDB.id == project_id).first()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # If generic -> named replacements requested, update project team members
    for swap in refresh_req.resource_swaps:
        named_res = db.query(ResourceDB).filter(ResourceDB.id == swap.named_resource_id).first()
        if named_res:
            # Ensure named resource is in project team
            existing_team = db.query(ProjectTeamResourceDB).filter(
                ProjectTeamResourceDB.project_id == proj.id,
                ProjectTeamResourceDB.resource_id == named_res.id,
            ).first()
            if not existing_team:
                db.add(ProjectTeamResourceDB(project_id=proj.id, resource_id=named_res.id))

    db.commit()

    # Generate refreshed template with updated rates, calendars, and resources
    return export_project_template_by_id(project_id=project_id, db=db)


# --- Entra ID (Azure AD) Selective Directory Integration ---

@router.get("/api/entra/status", response_model=EntraStatusResponse, tags=["Entra ID"])
def get_entra_status(user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"]))):
    """
    Returns connection and configuration status of Microsoft Entra ID.
    """
    res = entra_graph_service.test_connection()
    return EntraStatusResponse(
        configured=res.get("configured", False),
        connected=res.get("connected", False),
        mode=res.get("mode", "LOCAL_FALLBACK"),
        tenant_id=res.get("tenant_id") or (settings.AZURE_AD_TENANT_ID if settings.AZURE_AD_TENANT_ID else None),
        client_id=res.get("client_id") or (settings.AZURE_AD_CLIENT_ID if settings.AZURE_AD_CLIENT_ID else None),
        tenant_name=res.get("tenant_name"),
        message=res.get("message", ""),
    )


@router.post("/api/entra/config", response_model=EntraStatusResponse, tags=["Entra ID"])
def save_entra_config(
    cfg: EntraConfigUpdate,
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    """
    Saves Microsoft Entra ID connection credentials (Tenant ID, Client ID, Client Secret)
    and verifies live connection to Microsoft Graph.
    """
    old_tid = settings.AZURE_AD_TENANT_ID
    old_cid = settings.AZURE_AD_CLIENT_ID
    old_sec = settings.AZURE_AD_CLIENT_SECRET

    settings.AZURE_AD_TENANT_ID = cfg.tenant_id.strip()
    settings.AZURE_AD_CLIENT_ID = cfg.client_id.strip()
    settings.AZURE_AD_CLIENT_SECRET = cfg.client_secret.strip()

    test_res = entra_graph_service.test_connection()
    if not test_res.get("connected"):
        settings.AZURE_AD_TENANT_ID = old_tid
        settings.AZURE_AD_CLIENT_ID = old_cid
        settings.AZURE_AD_CLIENT_SECRET = old_sec
        raise HTTPException(
            status_code=400,
            detail=f"Entra ID connection test failed: {test_res.get('message', 'Invalid credentials')}",
        )

    # Persist into .env file
    env_path = ".env"
    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    new_lines = [
        line for line in lines
        if not any(line.strip().startswith(k + "=") for k in ("AZURE_AD_TENANT_ID", "AZURE_AD_CLIENT_ID", "AZURE_AD_CLIENT_SECRET"))
    ]
    new_lines.append(f"AZURE_AD_TENANT_ID={settings.AZURE_AD_TENANT_ID}\n")
    new_lines.append(f"AZURE_AD_CLIENT_ID={settings.AZURE_AD_CLIENT_ID}\n")
    new_lines.append(f"AZURE_AD_CLIENT_SECRET={settings.AZURE_AD_CLIENT_SECRET}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return EntraStatusResponse(
        configured=True,
        connected=True,
        mode="LIVE",
        tenant_id=settings.AZURE_AD_TENANT_ID,
        client_id=settings.AZURE_AD_CLIENT_ID,
        tenant_name=test_res.get("tenant_name"),
        message=f"Successfully connected to Microsoft Entra ID ({test_res.get('tenant_name')})",
    )


@router.get("/api/entra/users", response_model=List[EntraUserSchema], tags=["Entra ID"])
def search_entra_users(
    q: str = Query("", description="Search term for display name, email, or UPN"),
    limit: int = Query(15, ge=1, le=50),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    """
    Searches Microsoft Entra ID directory users.
    Enables selective user lookups rather than dumping all tenant users into the project pool.
    """
    return entra_graph_service.search_users(query=q, limit=limit)


@router.get("/api/entra/user", response_model=Optional[EntraUserSchema], tags=["Entra ID"])
def get_entra_user(
    email: str = Query(..., description="User email or UPN to look up"),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    """
    Looks up a single Entra ID directory user by email or UPN.
    """
    user_info = entra_graph_service.get_user_by_email(email)
    if not user_info:
        raise HTTPException(status_code=404, detail=f"User with email '{email}' not found in Entra ID")
    return user_info


@router.get("/api/entra/groups", response_model=List[EntraGroupSchema], tags=["Entra ID"])
def search_entra_groups(
    q: str = Query("", description="Search term for security group name"),
    limit: int = Query(20, ge=1, le=50),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    """
    Searches Microsoft Entra ID security groups.
    """
    return entra_graph_service.search_security_groups(query=q, limit=limit)


@router.get("/api/entra/groups/{group_id}/members", response_model=List[EntraUserSchema], tags=["Entra ID"])
def get_entra_group_members(
    group_id: str,
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    """
    Lists user members belonging to an Entra ID security group.
    """
    return entra_graph_service.get_group_members(group_id=group_id)


# --- Portal User Access Management ---

@router.get("/api/users", response_model=List[PortalUserModel], tags=["Portal Users"])
def list_portal_users(
    role: Optional[str] = Query(None),
    include_inactive: bool = Query(True),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    """
    Lists authorized portal users and their role assignments.
    """
    query = db.query(PortalUserDB)
    if not include_inactive:
        query = query.filter(PortalUserDB.is_active == True)
    if role:
        query = query.filter(PortalUserDB.role == role)
    return query.order_by(PortalUserDB.display_name.asc()).all()


@router.post("/api/users/add-by-email", response_model=PortalUserModel, status_code=status.HTTP_201_CREATED, tags=["Portal Users"])
def add_portal_user_by_email(
    req: PortalUserCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    """
    Grants portal access to a specific Entra ID user by email.
    Optionally also registers them in the Master Resource Pool.
    """
    # Look up user info from Entra ID if display name not provided
    entra_info = entra_graph_service.get_user_by_email(req.email)
    display_name = req.display_name or (entra_info["display_name"] if entra_info else req.email.split("@")[0].title())
    entra_oid = entra_info["id"] if entra_info else None
    dept = req.department or (entra_info.get("department") if entra_info else "Project Management")

    # Check if user already in PortalUserDB
    existing_user = db.query(PortalUserDB).filter(PortalUserDB.email.ilike(req.email.strip())).first()
    if existing_user:
        if not existing_user.is_active:
            # Reactivate
            existing_user.is_active = True
            existing_user.role = req.role
            existing_user.display_name = display_name
            db.commit()
            db.refresh(existing_user)
            return existing_user
        raise HTTPException(status_code=400, detail=f"User '{req.email}' already has portal access (Role: {existing_user.role})")

    new_user = PortalUserDB(
        email=req.email.strip().lower(),
        display_name=display_name,
        entra_oid=entra_oid,
        role=req.role,
        is_active=True,
        source="EMAIL",
    )
    db.add(new_user)

    # Optionally add as Resource into Master Resource Pool
    if req.add_as_resource:
        existing_res = db.query(ResourceDB).filter(
            (ResourceDB.email.ilike(req.email.strip())) | (ResourceDB.ad_upn.ilike(req.email.strip()))
        ).first()
        if not existing_res:
            res_db = ResourceDB(
                name=display_name,
                email=req.email.strip().lower(),
                ad_upn=req.email.strip().lower(),
                department=dept,
                resource_type=ResourceTypeEnum.WORK,
                resource_kind=ResourceKindEnum.NAMED,
                is_generic=False,
                is_active=True,
                base_calendar_id=req.base_calendar_id,
            )
            db.add(res_db)
            db.flush()

            # Add default rate table A
            rate_db = RatePeriodDB(
                resource_id=res_db.id,
                rate_table=RateTableEnum.A,
                standard_rate=req.standard_rate,
                overtime_rate=0.0,
                cost_per_use=0.0,
                effective_date=date.today(),
                created_by=user.email,
            )
            db.add(rate_db)

    # Audit log
    audit = AuditLogDB(
        entity_type="PORTAL_USER",
        entity_id=req.email,
        action="CREATE",
        changed_by=user.email,
        details=f"Granted portal access to '{display_name}' ({req.email}) with role '{req.role}'",
    )
    db.add(audit)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/api/users/import-group", response_model=GroupImportResult, tags=["Portal Users"])
def import_portal_users_from_group(
    req: GroupImportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    """
    Imports selected members of an Entra ID security group as portal users and/or project resources.
    """
    members = entra_graph_service.get_group_members(group_id=req.group_id)
    if not members:
        # Check if group exists
        groups = entra_graph_service.search_security_groups()
        matched = next((g for g in groups if g["id"] == req.group_id), None)
        group_name = matched["display_name"] if matched else req.group_name or req.group_id
    else:
        group_name = req.group_name or "Entra ID Security Group"

    users_added = 0
    users_skipped = 0
    resources_added = 0
    resources_skipped = 0
    details = []

    # If selected_emails specified, filter members
    target_members = [
        m for m in members
        if not req.selected_emails or m["email"].lower() in [e.lower() for e in req.selected_emails]
    ]

    for m in target_members:
        email = m["email"].strip().lower()
        dname = m["display_name"]
        dept = m.get("department") or "Engineering & Operations"

        # 1. Process Portal User
        if req.target in ("USERS", "BOTH"):
            existing_user = db.query(PortalUserDB).filter(PortalUserDB.email.ilike(email)).first()
            if existing_user:
                users_skipped += 1
            else:
                new_u = PortalUserDB(
                    email=email,
                    display_name=dname,
                    entra_oid=m.get("id"),
                    role=req.user_role,
                    is_active=True,
                    source="SECURITY_GROUP",
                    group_name=group_name,
                )
                db.add(new_u)
                users_added += 1
                details.append(f"User access added: {dname} ({email}) as {req.user_role}")

        # 2. Process Resource Pool
        if req.target in ("RESOURCES", "BOTH"):
            existing_res = db.query(ResourceDB).filter(
                (ResourceDB.email.ilike(email)) | (ResourceDB.ad_upn.ilike(email))
            ).first()
            if existing_res:
                resources_skipped += 1
            else:
                res_db = ResourceDB(
                    name=dname,
                    email=email,
                    ad_upn=m.get("upn") or email,
                    department=dept,
                    resource_type=ResourceTypeEnum.WORK,
                    resource_kind=ResourceKindEnum.NAMED,
                    is_generic=False,
                    is_active=True,
                    base_calendar_id=req.default_calendar_id,
                )
                db.add(res_db)
                db.flush()

                rate_db = RatePeriodDB(
                    resource_id=res_db.id,
                    rate_table=RateTableEnum.A,
                    standard_rate=req.default_rate,
                    overtime_rate=0.0,
                    cost_per_use=0.0,
                    effective_date=date.today(),
                    created_by=user.email,
                )
                db.add(rate_db)
                resources_added += 1
                details.append(f"Resource pool added: {dname} ({dept})")

    # Audit log
    audit = AuditLogDB(
        entity_type="SECURITY_GROUP",
        entity_id=req.group_id,
        action="IMPORT",
        changed_by=user.email,
        details=f"Imported from '{group_name}': {users_added} users, {resources_added} resources",
    )
    db.add(audit)
    db.commit()

    return GroupImportResult(
        group_id=req.group_id,
        group_name=group_name,
        target=req.target,
        total_members=len(target_members),
        users_added=users_added,
        users_skipped=users_skipped,
        resources_added=resources_added,
        resources_skipped=resources_skipped,
        details=details,
    )


@router.put("/api/users/{user_id}", response_model=PortalUserModel, tags=["Portal Users"])
def update_portal_user(
    user_id: int,
    req: PortalUserUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    """
    Updates role or activation status for a portal user.
    """
    p_user = db.query(PortalUserDB).filter(PortalUserDB.id == user_id).first()
    if not p_user:
        raise HTTPException(status_code=404, detail="Portal user not found")

    if req.role is not None:
        p_user.role = req.role
    if req.is_active is not None:
        p_user.is_active = req.is_active

    db.commit()
    db.refresh(p_user)
    return p_user


@router.delete("/api/users/{user_id}", tags=["Portal Users"])
def delete_portal_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin"])),
):
    """
    Deactivates portal access for a user.
    """
    p_user = db.query(PortalUserDB).filter(PortalUserDB.id == user_id).first()
    if not p_user:
        raise HTTPException(status_code=404, detail="Portal user not found")

    if p_user.email.lower() == user.email.lower():
        raise HTTPException(status_code=400, detail="Cannot deactivate your own administrator account")

    p_user.is_active = False
    db.commit()
    return {"message": f"User access deactivated for '{p_user.email}'"}


# --- Resource Management from Entra ID ---

@router.post("/api/resources/add-by-email", response_model=ResourceModel, status_code=status.HTTP_201_CREATED, tags=["Resources"])
def add_resource_from_entra_by_email(
    req: ResourceAddByEmailRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    """
    Selectively adds a single user from Entra ID into the Master Resource Pool.
    Prevents adding all tenant users at once.
    """
    email_clean = req.email.strip().lower()
    existing = db.query(ResourceDB).filter(
        (ResourceDB.email.ilike(email_clean)) | (ResourceDB.ad_upn.ilike(email_clean))
    ).first()
    if existing:
        if not existing.is_active:
            existing.is_active = True
            db.commit()
            db.refresh(existing)
            return existing
        raise HTTPException(status_code=400, detail=f"Resource with email '{email_clean}' already exists in Resource Pool")

    entra_info = entra_graph_service.get_user_by_email(email_clean)
    display_name = req.display_name or (entra_info["display_name"] if entra_info else email_clean.split("@")[0].title())
    dept = req.department or (entra_info.get("department") if entra_info else "Engineering & Operations")

    new_res = ResourceDB(
        name=display_name,
        email=email_clean,
        ad_upn=email_clean,
        department=dept,
        resource_type=ResourceTypeEnum.WORK,
        resource_kind=ResourceKindEnum.NAMED,
        is_generic=False,
        is_active=True,
        base_calendar_id=req.base_calendar_id,
    )
    db.add(new_res)
    db.flush()

    # Create default Rate Table A entry
    rate_db = RatePeriodDB(
        resource_id=new_res.id,
        rate_table=RateTableEnum.A,
        standard_rate=req.standard_rate,
        overtime_rate=req.overtime_rate,
        cost_per_use=0.0,
        effective_date=date.today(),
        created_by=user.email,
    )
    db.add(rate_db)

    # Audit log
    audit = AuditLogDB(
        entity_type="RESOURCE",
        entity_id=str(new_res.id),
        action="CREATE",
        changed_by=user.email,
        details=f"Added Entra ID resource '{display_name}' ({email_clean}) to Master Pool with rate €{req.standard_rate:.2f}/h",
    )
    db.add(audit)
    db.commit()
    db.refresh(new_res)

    rates = [
        CostRateItem(
            rate_table=RateTableEnum.A,
            standard_rate=req.standard_rate,
            overtime_rate=req.overtime_rate,
            cost_per_use=0.0,
            effective_date=date.today(),
        )
    ]
    return ResourceModel(
        id=new_res.id,
        guid=new_res.guid,
        ad_upn=new_res.ad_upn,
        name=new_res.name,
        email=new_res.email,
        department=new_res.department,
        resource_type=new_res.resource_type,
        resource_kind=new_res.resource_kind,
        is_generic=new_res.is_generic,
        is_active=new_res.is_active,
        base_calendar_id=new_res.base_calendar_id,
        rates=rates,
        custom_field_values={},
    )


@router.post("/api/resources/import-group", response_model=GroupImportResult, tags=["Resources"])
def import_resources_from_entra_group(
    req: GroupImportRequest,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_roles(["Admin", "ResourceManager"])),
):
    """
    Selectively imports members of an Entra ID security group into the Master Resource Pool.
    """
    req.target = "RESOURCES"
    return import_portal_users_from_group(req=req, db=db, user=user)



