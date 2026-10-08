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


class CalendarModel(BaseModel):
    id: int
    name: str
    country_code: str = Field(default="LT", description="ISO 3166-1 alpha-2 country code")
    is_base_calendar: bool = True
    base_calendar_uid: Optional[int] = -1
    exceptions: List[CalendarException] = []


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
