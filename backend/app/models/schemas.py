"""
Pydantic data models and schemas for MS Project Centralized Resource & Template Hub.
"""

from datetime import date, datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from backend.app.models.enums import (
    CustomFieldEntityEnum,
    CustomFieldTypeEnum,
    RateTableEnum,
    ResourceKindEnum,
    ResourceTypeEnum,
    StageStatusEnum,
)


class CostRateItem(BaseModel):
    rate_table: RateTableEnum = Field(default=RateTableEnum.A, description="Cost Rate Table slot (A-E)")
    standard_rate: float = Field(..., description="Hourly or unit standard cost")
    overtime_rate: float = Field(default=0.0, description="Overtime hourly rate")
    cost_per_use: float = Field(default=0.0, description="One-time cost per task assignment")
    effective_date: Optional[date] = Field(default=None, description="Start date for rate validity (RatesFrom)")
    rates_to: Optional[date] = Field(default=None, description="End date for rate validity (RatesTo)")


class CalendarException(BaseModel):
    name: str = Field(..., description="Exception or holiday title, e.g. 'Labour Day'")
    from_date: date
    to_date: date
    working: bool = False


class WorkingShiftModel(BaseModel):
    from_time: str = Field(..., description="Shift start time e.g. '13:00:00'")
    to_time: str = Field(..., description="Shift finish time e.g. '17:00:00'")


class WeekDayModel(BaseModel):
    day_type: int = Field(..., description="MS Project DayType (1=Sunday, 2=Monday, ..., 7=Saturday)")
    day_working: bool = Field(default=True, description="True if working day, False if weekend/day off")
    working_times: List[WorkingShiftModel] = Field(default_factory=list, description="Working shifts for the day")


class CalendarModel(BaseModel):
    id: int
    name: str
    country_code: str = Field(default="LT", description="ISO 3166-1 alpha-2 country code")
    is_base_calendar: bool = True
    base_calendar_uid: Optional[int] = -1
    is_active: bool = True
    weekdays: List[WeekDayModel] = Field(default_factory=list)
    exceptions: List[CalendarException] = Field(default_factory=list)


class CalendarCreate(BaseModel):
    name: str
    country_code: str = "LT"
    is_active: bool = True
    weekdays: Optional[List[WeekDayModel]] = None


class CalendarUpdate(BaseModel):
    name: Optional[str] = None
    country_code: Optional[str] = None
    is_active: Optional[bool] = None


class CalendarWeekdaysUpdate(BaseModel):
    weekdays: List[WeekDayModel]


class ResourceModel(BaseModel):
    id: int
    guid: str
    ad_upn: Optional[str] = None
    name: str
    email: Optional[str] = None
    department: Optional[str] = None
    resource_type: ResourceTypeEnum = ResourceTypeEnum.WORK
    resource_kind: ResourceKindEnum = ResourceKindEnum.NAMED
    is_generic: bool = False
    is_active: bool = True  # Soft delete constraint
    base_calendar_id: int = 1
    rates: List[CostRateItem] = []
    custom_field_values: Dict[str, str] = Field(default_factory=dict, description="Field Name/Alias -> Value")


class CustomFieldDefinition(BaseModel):
    field_id: Optional[str] = None
    field_name: str
    entity: CustomFieldEntityEnum = CustomFieldEntityEnum.RESOURCE
    field_type: CustomFieldTypeEnum = CustomFieldTypeEnum.TEXT
    slot_number: int = 1
    alias: Optional[str] = None
    default_value: Optional[str] = None


class ProjectTemplateRequest(BaseModel):
    project_id: Optional[int] = None
    project_guid: Optional[str] = None
    project_erp_number: Optional[str] = Field(default=None, description="ERP project number, e.g. '26-0537'")
    project_title: str
    company_name: Optional[str] = "Enterprise Global"
    start_date: date = Field(default_factory=date.today)
    calendar_id: int = 1
    selected_resource_ids: List[int] = Field(default_factory=list)
    budget_cost: Optional[float] = Field(default=None, description="Project budget set by Finance Manager")
    custom_fields: List[CustomFieldDefinition] = Field(default_factory=list)
    project_custom_values: Dict[str, str] = Field(default_factory=dict)


class ProjectCreate(BaseModel):
    erp_number: str = Field(..., description="Unique ERP project code, e.g. '26-0537'")
    name: str = Field(..., description="Project name")
    owner: str = Field(..., description="Project Manager name or email")
    calendar_id: int = Field(default=1)
    start_date: date = Field(default_factory=date.today)
    budget_cost: Optional[float] = Field(default=0.0)
    team_resource_ids: List[int] = Field(default_factory=list)


class ProjectBudgetUpdate(BaseModel):
    budget_cost: float = Field(..., ge=0.0, description="Project budget cost set by Finance Manager")


class StageDefinitionSchema(BaseModel):
    id: int
    name: str
    code: str
    sort_order: int
    is_active: bool


class StageDefinitionCreate(BaseModel):
    name: str
    code: str
    sort_order: int = 0


class StageStatusUpdate(BaseModel):
    status: StageStatusEnum


class ProjectSnapshotCreate(BaseModel):
    percent_complete: float = 0.0
    percent_work_complete: float = 0.0
    start_date: Optional[date] = None
    finish_date: Optional[date] = None
    baseline_finish: Optional[date] = None
    actual_cost: float = 0.0
    cost: float = 0.0
    baseline_cost: float = 0.0
    baseline_budget: float = 0.0
    budget_cost: float = 0.0
    source: str = "MANUAL"


class ResourceSwapItem(BaseModel):
    generic_resource_name: str
    named_resource_id: int


class ProjectRefreshRequest(BaseModel):
    resource_swaps: List[ResourceSwapItem] = Field(default_factory=list)


# --- Entra ID & Portal User Schemas ---

class EntraUserSchema(BaseModel):
    id: str
    display_name: str
    email: str
    upn: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None


class EntraGroupSchema(BaseModel):
    id: str
    display_name: str
    mail: Optional[str] = None
    description: Optional[str] = None
    security_enabled: bool = True
    members_count: int = 0


class PortalUserModel(BaseModel):
    id: int
    email: str
    display_name: str
    entra_oid: Optional[str] = None
    role: str
    is_active: bool
    source: str
    group_name: Optional[str] = None
    created_at: datetime


class PortalUserCreate(BaseModel):
    email: str
    display_name: Optional[str] = None
    role: str = "PM"  # Admin, PM, FinanceManager, ResourceManager, Viewer
    add_as_resource: bool = False
    department: Optional[str] = None
    base_calendar_id: int = 1
    standard_rate: float = 0.0


class PortalUserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


class ResourceAddByEmailRequest(BaseModel):
    email: str
    display_name: Optional[str] = None
    department: Optional[str] = None
    base_calendar_id: int = 1
    standard_rate: float = 0.0
    overtime_rate: float = 0.0


class GroupImportRequest(BaseModel):
    group_id: str
    group_name: Optional[str] = None
    target: str = "BOTH"  # "USERS", "RESOURCES", "BOTH"
    user_role: str = "PM"
    selected_emails: Optional[List[str]] = None  # None = import all members
    default_calendar_id: int = 1
    default_rate: float = 0.0


class GroupImportResult(BaseModel):
    group_id: str
    group_name: str
    target: str
    total_members: int
    users_added: int
    users_skipped: int
    resources_added: int
    resources_skipped: int
    details: List[str] = Field(default_factory=list)


class EntraConfigUpdate(BaseModel):
    tenant_id: str
    client_id: str
    client_secret: str


class EntraStatusResponse(BaseModel):
    configured: bool
    connected: bool
    mode: str  # "LIVE" or "LOCAL_FALLBACK" or "ERROR"
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    tenant_name: Optional[str] = None
    message: str




