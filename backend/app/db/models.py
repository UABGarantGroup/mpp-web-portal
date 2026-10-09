"""
SQLAlchemy 2.0 ORM Models for Centralized Resource Management and Project Hub.
Includes:
- Calendars & Calendar Exceptions
- Resources (Named & Generic) with soft-delete support
- Multi-tier Cost Rate Tables (A-E) with chronological history
- Custom Enterprise Fields and Pick-list Lookup Values
- Project Master entities
- Audit Logging for Finance and Admin tracking
"""

from datetime import date, datetime
import uuid
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from backend.app.db.session import Base
from backend.app.models.enums import (
    CustomFieldEntityEnum,
    CustomFieldTypeEnum,
    RateTableEnum,
    ResourceKindEnum,
    ResourceTypeEnum,
    StageStatusEnum,
)


class CalendarDB(Base):
    __tablename__ = "calendars"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    country_code = Column(String(10), default="LT", nullable=False)
    is_base_calendar = Column(Boolean, default=True, nullable=False)
    base_calendar_uid = Column(Integer, default=-1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    exceptions = relationship(
        "CalendarExceptionDB",
        back_populates="calendar",
        cascade="all, delete-orphan",
        order_by="CalendarExceptionDB.from_date",
    )
    weekdays = relationship(
        "CalendarWeekdayDB",
        back_populates="calendar",
        cascade="all, delete-orphan",
        order_by="CalendarWeekdayDB.day_type",
    )
    resources = relationship("ResourceDB", back_populates="base_calendar")


class CalendarWeekdayDB(Base):
    __tablename__ = "calendar_weekdays"

    id = Column(Integer, primary_key=True, index=True)
    calendar_id = Column(Integer, ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False, index=True)
    day_type = Column(Integer, nullable=False)  # 1=Sunday, 2=Monday, ..., 7=Saturday
    day_working = Column(Boolean, default=True, nullable=False)

    calendar = relationship("CalendarDB", back_populates="weekdays")
    working_times = relationship(
        "CalendarWorkingShiftDB",
        back_populates="weekday",
        cascade="all, delete-orphan",
        order_by="CalendarWorkingShiftDB.from_time",
    )


class CalendarWorkingShiftDB(Base):
    __tablename__ = "calendar_working_shifts"

    id = Column(Integer, primary_key=True, index=True)
    weekday_id = Column(Integer, ForeignKey("calendar_weekdays.id", ondelete="CASCADE"), nullable=False, index=True)
    from_time = Column(String(8), nullable=False)  # "HH:MM:SS" e.g. "13:00:00"
    to_time = Column(String(8), nullable=False)    # "HH:MM:SS" e.g. "17:00:00"

    weekday = relationship("CalendarWeekdayDB", back_populates="working_times")


class CalendarExceptionDB(Base):
    __tablename__ = "calendar_exceptions"

    id = Column(Integer, primary_key=True, index=True)
    calendar_id = Column(Integer, ForeignKey("calendars.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    from_date = Column(Date, nullable=False, index=True)
    to_date = Column(Date, nullable=False)
    working = Column(Boolean, default=False, nullable=False)
    source = Column(String(50), default="MANUAL", nullable=False)  # "MANUAL" or "IMPORT"
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    calendar = relationship("CalendarDB", back_populates="exceptions")


class ResourceDB(Base):
    __tablename__ = "resources"

    id = Column(Integer, primary_key=True, index=True)
    guid = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()), nullable=False)
    ad_upn = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    department = Column(String(255), nullable=True, index=True)
    resource_type = Column(SQLEnum(ResourceTypeEnum), default=ResourceTypeEnum.WORK, nullable=False)
    resource_kind = Column(SQLEnum(ResourceKindEnum), default=ResourceKindEnum.NAMED, nullable=False)
    is_generic = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)  # Soft delete
    base_calendar_id = Column(Integer, ForeignKey("calendars.id"), default=1, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    base_calendar = relationship("CalendarDB", back_populates="resources")
    rates = relationship(
        "RatePeriodDB",
        back_populates="resource",
        cascade="all, delete-orphan",
        order_by="RatePeriodDB.effective_date",
    )
    field_values = relationship(
        "ResourceFieldValueDB",
        back_populates="resource",
        cascade="all, delete-orphan",
    )


class RatePeriodDB(Base):
    __tablename__ = "rate_periods"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    rate_table = Column(SQLEnum(RateTableEnum), default=RateTableEnum.A, nullable=False)
    standard_rate = Column(Float, default=0.0, nullable=False)
    overtime_rate = Column(Float, default=0.0, nullable=False)
    cost_per_use = Column(Float, default=0.0, nullable=False)
    effective_date = Column(Date, nullable=True, index=True)
    rates_to = Column(Date, nullable=True)
    created_by = Column(String(255), nullable=True)  # Project Finance Manager identity
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    resource = relationship("ResourceDB", back_populates="rates")


class CustomFieldDB(Base):
    __tablename__ = "custom_fields"

    id = Column(Integer, primary_key=True, index=True)
    field_name = Column(String(255), nullable=False)
    entity = Column(SQLEnum(CustomFieldEntityEnum), default=CustomFieldEntityEnum.RESOURCE, nullable=False)
    field_type = Column(SQLEnum(CustomFieldTypeEnum), default=CustomFieldTypeEnum.TEXT, nullable=False)
    slot_number = Column(Integer, default=1, nullable=False)
    field_id = Column(String(32), nullable=False)  # Canonical MSPDI field id e.g. "205520904"
    alias = Column(String(255), nullable=True)
    default_value = Column(String(255), nullable=True)

    lookup_values = relationship(
        "FieldLookupValueDB",
        back_populates="custom_field",
        cascade="all, delete-orphan",
        order_by="FieldLookupValueDB.sort_order",
    )
    resource_values = relationship("ResourceFieldValueDB", back_populates="custom_field", cascade="all, delete-orphan")


class FieldLookupValueDB(Base):
    __tablename__ = "field_lookup_values"

    id = Column(Integer, primary_key=True, index=True)
    custom_field_id = Column(Integer, ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(String(255), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)

    custom_field = relationship("CustomFieldDB", back_populates="lookup_values")


class ResourceFieldValueDB(Base):
    __tablename__ = "resource_field_values"

    id = Column(Integer, primary_key=True, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    custom_field_id = Column(Integer, ForeignKey("custom_fields.id", ondelete="CASCADE"), nullable=False, index=True)
    value = Column(String(500), nullable=False)

    resource = relationship("ResourceDB", back_populates="field_values")
    custom_field = relationship("CustomFieldDB", back_populates="resource_values")


class ProjectDB(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    project_guid = Column(String(64), unique=True, index=True, default=lambda: str(uuid.uuid4()), nullable=False)
    erp_number = Column(String(64), unique=True, index=True, nullable=False)  # e.g., "26-0537"
    name = Column(String(255), nullable=False)
    owner = Column(String(255), nullable=True, index=True)  # PM name / email
    start_date = Column(Date, nullable=True)
    calendar_id = Column(Integer, ForeignKey("calendars.id"), default=1, nullable=False)
    budget_cost = Column(Float, default=0.0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_updated_by = Column(String(255), nullable=True)  # User email/name who last updated schedule or project
    last_updated_at = Column(DateTime, nullable=True)     # Timestamp of last update / schedule upload

    stage_statuses = relationship("ProjectStageStatusDB", back_populates="project", cascade="all, delete-orphan")
    snapshots = relationship("ProjectSnapshotDB", back_populates="project", cascade="all, delete-orphan", order_by="desc(ProjectSnapshotDB.recorded_at)")
    team_members = relationship("ProjectTeamResourceDB", back_populates="project", cascade="all, delete-orphan")


class ProjectTeamResourceDB(Base):
    __tablename__ = "project_team_resources"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)

    project = relationship("ProjectDB", back_populates="team_members")
    resource = relationship("ResourceDB")


class StageDefinitionDB(Base):
    __tablename__ = "stage_definitions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(64), unique=True, nullable=False)  # e.g. "tabelis", "saskaita"
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)  # Blocked when False

    stage_statuses = relationship("ProjectStageStatusDB", back_populates="stage_definition", cascade="all, delete-orphan")


class ProjectStageStatusDB(Base):
    __tablename__ = "project_stage_statuses"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    stage_id = Column(Integer, ForeignKey("stage_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(SQLEnum(StageStatusEnum), default=StageStatusEnum.NOT_DONE, nullable=False)
    updated_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    project = relationship("ProjectDB", back_populates="stage_statuses")
    stage_definition = relationship("StageDefinitionDB", back_populates="stage_statuses")


class ProjectSnapshotDB(Base):
    __tablename__ = "project_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    percent_complete = Column(Float, default=0.0, nullable=False)
    percent_work_complete = Column(Float, default=0.0, nullable=False)
    start_date = Column(Date, nullable=True)
    finish_date = Column(Date, nullable=True)
    baseline_finish = Column(Date, nullable=True)
    actual_cost = Column(Float, default=0.0, nullable=False)
    cost = Column(Float, default=0.0, nullable=False)
    baseline_cost = Column(Float, default=0.0, nullable=False)
    baseline_budget = Column(Float, default=0.0, nullable=False)
    budget_cost = Column(Float, default=0.0, nullable=False)
    source = Column(String(50), default="MANUAL", nullable=False)  # "MANUAL" or "UPLOAD"
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    project = relationship("ProjectDB", back_populates="snapshots")


class AuditLogDB(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)  # "RESOURCE", "RATE", "BUDGET", "CALENDAR", "STAGE"
    entity_id = Column(String(64), nullable=False, index=True)
    action = Column(String(50), nullable=False)                   # "CREATE", "UPDATE", "SOFT_DELETE"
    changed_by = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class PortalUserDB(Base):
    """
    Authorized portal users and their role assignments.
    Prevents blanket access for all Entra ID directory accounts.
    Allows Admins to selectively grant access by user email or security group.
    """
    __tablename__ = "portal_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    display_name = Column(String(255), nullable=False)
    entra_oid = Column(String(64), nullable=True, index=True)
    role = Column(String(50), default="PM", nullable=False)  # Admin, PM, FinanceManager, ResourceManager, Viewer
    is_active = Column(Boolean, default=True, nullable=False)
    source = Column(String(50), default="MANUAL", nullable=False)  # "EMAIL", "SECURITY_GROUP", "MANUAL"
    group_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


