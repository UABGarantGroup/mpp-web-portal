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
    CalendarException,
    CalendarModel,
    CostRateItem,
    CustomFieldDefinition,
    ProjectTemplateRequest,
    ResourceModel,
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

@router.get("/api/calendars", response_model=List[CalendarModel], tags=["Calendars"])
def list_calendars(db: Session = Depends(get_db)):
    cal_dbs = db.query(CalendarDB).all()
    results = []
    for c in cal_dbs:
        exceptions = [
            CalendarException(
                name=e.name,
                from_date=e.from_date,
                to_date=e.to_date,
                working=e.working,
            )
            for e in c.exceptions
        ]
        results.append(
            CalendarModel(
                id=c.id,
                name=c.name,
                country_code=c.country_code,
                is_base_calendar=c.is_base_calendar,
                base_calendar_uid=c.base_calendar_uid,
                exceptions=exceptions,
            )
        )
    return results


@router.get("/api/calendars/countries", tags=["Calendars"])
def get_countries():
    return get_supported_countries()


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

    return CalendarModel(
        id=cal.id,
        name=cal.name,
        country_code=cal.country_code,
        is_base_calendar=cal.is_base_calendar,
        base_calendar_uid=cal.base_calendar_uid,
        exceptions=[
            CalendarException(name=e.name, from_date=e.from_date, to_date=e.to_date, working=e.working)
            for e in cal.exceptions
        ],
    )


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
    calendars_dict = {
        c.id: CalendarModel(
            id=c.id,
            name=c.name,
            country_code=c.country_code,
            is_base_calendar=c.is_base_calendar,
            base_calendar_uid=c.base_calendar_uid,
            exceptions=[
                CalendarException(name=e.name, from_date=e.from_date, to_date=e.to_date, working=e.working)
                for e in c.exceptions
            ],
        )
        for c in cal_dbs
    }

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
