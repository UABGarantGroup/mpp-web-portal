"""
REST API routes for MS Project Centralized Resource & Template Hub.
"""

from datetime import date
from typing import Dict, List, Optional
import urllib.parse
from fastapi import APIRouter, HTTPException, Query, Response, status

from backend.app.models.enums import RateTableEnum, ResourceKindEnum, ResourceTypeEnum
from backend.app.models.schemas import (
    CalendarException,
    CalendarModel,
    CostRateItem,
    CustomFieldDefinition,
    ProjectTemplateRequest,
    ResourceModel,
)
from backend.app.services.holiday_service import fetch_country_holidays, get_supported_countries
from backend.app.services.xml_generator import build_ms_project_xml

router = APIRouter()

# --- In-Memory Repository for Phase 0 (will connect to DB in Phase 1) ---

CALENDARS_DB: Dict[int, CalendarModel] = {
    1: CalendarModel(
        id=1,
        name="Lithuania – Standard Enterprise Calendar",
        country_code="LT",
        is_base_calendar=True,
        exceptions=[
            CalendarException(name="New Year's Day", from_date=date(2026, 1, 1), to_date=date(2026, 1, 1), working=False),
            CalendarException(name="Day of Restoration of the State of Lithuania", from_date=date(2026, 2, 16), to_date=date(2026, 2, 16), working=False),
            CalendarException(name="Day of Restoration of Independence of Lithuania", from_date=date(2026, 3, 11), to_date=date(2026, 3, 11), working=False),
            CalendarException(name="Labour Day", from_date=date(2026, 5, 1), to_date=date(2026, 5, 1), working=False),
        ],
    ),
    2: CalendarModel(
        id=2,
        name="Norway – Standard Offshore Calendar",
        country_code="NO",
        is_base_calendar=True,
        exceptions=[
            CalendarException(name="New Year's Day", from_date=date(2026, 1, 1), to_date=date(2026, 1, 1), working=False),
            CalendarException(name="Constitution Day", from_date=date(2026, 5, 17), to_date=date(2026, 5, 17), working=False),
        ],
    ),
}

RESOURCES_DB: Dict[int, ResourceModel] = {
    1: ResourceModel(
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
        rates=[
            CostRateItem(rate_table=RateTableEnum.A, standard_rate=45.00, overtime_rate=67.50, effective_date=date(2026, 1, 1)),
            CostRateItem(rate_table=RateTableEnum.B, standard_rate=55.00, overtime_rate=82.50, effective_date=date(2026, 1, 1)),
            CostRateItem(rate_table=RateTableEnum.C, standard_rate=75.00, overtime_rate=112.50, effective_date=date(2026, 1, 1)),
        ],
        custom_field_values={"Cost Center": "ENG-101"},
    ),
    2: ResourceModel(
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
        rates=[
            CostRateItem(rate_table=RateTableEnum.A, standard_rate=50.00, overtime_rate=75.00, effective_date=date(2026, 1, 1)),
            CostRateItem(rate_table=RateTableEnum.B, standard_rate=65.00, overtime_rate=97.50, effective_date=date(2026, 1, 1)),
        ],
        custom_field_values={"Cost Center": "PMO-200"},
    ),
    3: ResourceModel(
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
        rates=[
            CostRateItem(rate_table=RateTableEnum.A, standard_rate=40.00, overtime_rate=60.00, effective_date=date(2026, 1, 1)),
            CostRateItem(rate_table=RateTableEnum.C, standard_rate=70.00, overtime_rate=105.00, effective_date=date(2026, 1, 1)),
        ],
        custom_field_values={"Skill Level": "Senior"},
    ),
}


# --- System Endpoints ---

@router.get("/health", tags=["System"])
def health_check():
    return {"status": "healthy", "service": "mpp-template-engine", "version": "1.0.0"}


# --- Calendars & Holidays Endpoints ---

@router.get("/api/calendars", response_model=List[CalendarModel], tags=["Calendars"])
def list_calendars():
    return list(CALENDARS_DB.values())


@router.get("/api/calendars/countries", tags=["Calendars"])
def get_countries():
    return get_supported_countries()


@router.post("/api/calendars/{calendar_id}/import-holidays", response_model=CalendarModel, tags=["Calendars"])
def import_holidays(calendar_id: int, years: Optional[List[int]] = Query(None)):
    calendar = CALENDARS_DB.get(calendar_id)
    if not calendar:
        raise HTTPException(status_code=404, detail="Calendar not found")

    imported = fetch_country_holidays(calendar.country_code, years)
    for h in imported:
        # Avoid duplicate exceptions by name & date
        exists = any(exc.from_date == h["from_date"] and exc.name == h["name"] for exc in calendar.exceptions)
        if not exists:
            calendar.exceptions.append(CalendarException(**h))
    return calendar


@router.post("/api/calendars/{calendar_id}/exceptions", response_model=CalendarModel, tags=["Calendars"])
def add_calendar_exception(calendar_id: int, exception: CalendarException):
    calendar = CALENDARS_DB.get(calendar_id)
    if not calendar:
        raise HTTPException(status_code=404, detail="Calendar not found")
    calendar.exceptions.append(exception)
    return calendar


# --- Resources & Cost Rates Endpoints ---

@router.get("/api/resources", response_model=List[ResourceModel], tags=["Resources"])
def list_resources(
    department: Optional[str] = Query(None),
    kind: Optional[ResourceKindEnum] = Query(None),
    include_inactive: bool = Query(False),
):
    results = list(RESOURCES_DB.values())
    if not include_inactive:
        results = [r for r in results if r.is_active]
    if department:
        results = [r for r in results if r.department and r.department.lower() == department.lower()]
    if kind:
        results = [r for r in results if r.resource_kind == kind]
    return results


@router.post("/api/resources", response_model=ResourceModel, status_code=status.HTTP_201_CREATED, tags=["Resources"])
def create_resource(resource: ResourceModel):
    RESOURCES_DB[resource.id] = resource
    return resource


@router.delete("/api/resources/{resource_id}", response_model=ResourceModel, tags=["Resources"])
def soft_delete_resource(resource_id: int):
    res = RESOURCES_DB.get(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")
    # Soft delete: never hard delete from database
    res.is_active = False
    return res


@router.put("/api/resources/{resource_id}/rates", response_model=ResourceModel, tags=["Cost Rates"])
def update_resource_rates(resource_id: int, rates: List[CostRateItem]):
    res = RESOURCES_DB.get(resource_id)
    if not res:
        raise HTTPException(status_code=404, detail="Resource not found")
    res.rates = rates
    return res


# --- Template Export Endpoints ---

@router.post("/api/templates/export/xml", tags=["Export"])
def export_project_xml(template_req: ProjectTemplateRequest):
    """
    Generates and downloads a fully compliant MS Project XML template.
    """
    xml_content = build_ms_project_xml(
        template_req=template_req,
        calendars=CALENDARS_DB,
        resources=RESOURCES_DB,
    )

    clean_title = "".join(c for c in template_req.project_title if c.isalnum() or c in ("-", "_", " ")).strip()
    ascii_filename = f"{clean_title.replace(' ', '_').lower()}_template.xml"
    quoted_filename = urllib.parse.quote(f"{template_req.project_title}_template.xml")

    # RFC 5987 Content-Disposition for international characters
    content_disp = f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{quoted_filename}"

    return Response(
        content=xml_content,
        media_type="application/xml; charset=utf-8",
        headers={
            "Content-Disposition": content_disp
        },
    )
