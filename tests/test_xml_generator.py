"""
Unit tests for MS Project XML generator and schema compliance.
Verifies all Phase 0 architectural requirements.
"""

from datetime import date
import xml.etree.ElementTree as ET
import pytest

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
from backend.app.services.field_ids import (
    RESOURCE_FIELD_BASE,
    TASK_FIELD_BASE,
    get_field_id,
)
from backend.app.services.holiday_service import fetch_country_holidays, get_supported_countries
from backend.app.services.xml_generator import build_ms_project_xml


@pytest.fixture
def sample_data():
    calendar = CalendarModel(
        id=1,
        name="Lithuania Standard Calendar",
        country_code="LT",
        is_base_calendar=True,
        exceptions=[
            CalendarException(name="New Year", from_date=date(2026, 1, 1), to_date=date(2026, 1, 1), working=False),
            CalendarException(name="Labour Day", from_date=date(2026, 5, 1), to_date=date(2026, 5, 1), working=False),
        ],
    )
    calendars = {1: calendar}

    named_res = ResourceModel(
        id=101,
        guid="11111111-2222-3333-4444-555555555555",
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
    )

    generic_res = ResourceModel(
        id=202,
        guid="99999999-8888-7777-6666-555555555555",
        name="Mechanic (generic)",
        resource_type=ResourceTypeEnum.WORK,
        resource_kind=ResourceKindEnum.GENERIC,
        is_generic=True,
        is_active=True,
        base_calendar_id=1,
        rates=[
            CostRateItem(rate_table=RateTableEnum.A, standard_rate=40.00, overtime_rate=60.00, effective_date=date(2026, 1, 1)),
        ],
    )

    inactive_res = ResourceModel(
        id=303,
        guid="00000000-0000-0000-0000-000000000303",
        name="Former Employee",
        resource_type=ResourceTypeEnum.WORK,
        resource_kind=ResourceKindEnum.NAMED,
        is_generic=False,
        is_active=False,  # Soft-deleted
        base_calendar_id=1,
    )

    cost_res = ResourceModel(
        id=404,
        guid="00000000-0000-0000-0000-000000000404",
        name="Travel Expenses",
        resource_type=ResourceTypeEnum.COST,  # Must map to Type 2
        resource_kind=ResourceKindEnum.NAMED,
        is_generic=False,
        is_active=True,
        base_calendar_id=1,
    )

    resources = {101: named_res, 202: generic_res, 303: inactive_res, 404: cost_res}

    req = ProjectTemplateRequest(
        project_id=1,
        project_guid="aaaa-bbbb-cccc-dddd",
        project_erp_number="26-0537",
        project_title="26-0537 LA MANCHA KNUTSEN - assistance to Burckhardt",
        company_name="Enterprise Global",
        start_date=date(2026, 8, 25),
        calendar_id=1,
        selected_resource_ids=[101, 202, 303, 404],
        budget_cost=332459.00,
        custom_fields=[
            CustomFieldDefinition(field_name="Cost Center", entity=CustomFieldEntityEnum.RESOURCE, slot_number=1, alias="Cost Center"),
            CustomFieldDefinition(field_name="ERP Project Number", entity=CustomFieldEntityEnum.PROJECT, slot_number=1, alias="ERP Project Number"),
        ],
        project_custom_values={"ERP Project Number": "26-0537"},
    )

    return {"calendars": calendars, "resources": resources, "req": req}


def test_build_ms_project_xml_valid_structure(sample_data):
    xml_str = build_ms_project_xml(sample_data["req"], sample_data["calendars"], sample_data["resources"])
    assert xml_str.startswith("<?xml")

    # Strip XML namespace for clean assert checks
    root = ET.fromstring(xml_str)
    ns = {"p": "http://schemas.microsoft.com/project"}

    # Top-level project properties
    assert root.find("p:SaveVersion", ns).text == "14"
    assert root.find("p:Name", ns).text == "26-0537 LA MANCHA KNUTSEN - assistance to Burckhardt"
    assert root.find("p:CurrencyCode", ns).text == "EUR"
    assert root.find("p:ScheduleFromStart", ns).text == "1"


def test_project_summary_task_uid_0(sample_data):
    xml_str = build_ms_project_xml(sample_data["req"], sample_data["calendars"], sample_data["resources"])
    root = ET.fromstring(xml_str)
    ns = {"p": "http://schemas.microsoft.com/project"}

    summary_task = root.find("p:Tasks/p:Task[p:UID='0']", ns)
    assert summary_task is not None
    assert summary_task.find("p:ID", ns).text == "0"
    assert summary_task.find("p:Summary", ns).text == "1"
    assert summary_task.find("p:OutlineNumber", ns).text == "0"
    assert summary_task.find("p:OutlineLevel", ns).text == "0"

    # Project-level custom field value
    ext_val = summary_task.find("p:ExtendedAttribute/p:Value", ns)
    assert ext_val is not None
    assert ext_val.text == "26-0537"


def test_budget_resource_and_assignment_on_task_0(sample_data):
    xml_str = build_ms_project_xml(sample_data["req"], sample_data["calendars"], sample_data["resources"])
    root = ET.fromstring(xml_str)
    ns = {"p": "http://schemas.microsoft.com/project"}

    # Budget Resource must be Type 2 (Cost) and have IsBudget=1
    budget_res = root.find("p:Resources/p:Resource[p:UID='9999']", ns)
    assert budget_res is not None
    assert budget_res.find("p:Type", ns).text == "2"
    assert budget_res.find("p:IsBudget", ns).text == "1"
    assert budget_res.find("p:IsCostResource", ns).text == "1"

    # Budget Assignment must link TaskUID 0 to Budget Resource UID 9999 with BudgetCost
    budget_assign = root.find("p:Assignments/p:Assignment[p:TaskUID='0']", ns)
    assert budget_assign is not None
    assert budget_assign.find("p:ResourceUID", ns).text == "9999"
    assert budget_assign.find("p:BudgetCost", ns).text == "332459.00"
    # Standard Cost element should NOT be present on budget assignment
    assert budget_assign.find("p:Cost", ns) is None


def test_base_calendar_weekdays_and_exceptions(sample_data):
    xml_str = build_ms_project_xml(sample_data["req"], sample_data["calendars"], sample_data["resources"])
    root = ET.fromstring(xml_str)
    ns = {"p": "http://schemas.microsoft.com/project"}

    cal = root.find("p:Calendars/p:Calendar[p:UID='1']", ns)
    assert cal is not None
    assert cal.find("p:IsBaseCalendar", ns).text == "1"

    # WeekDays
    weekdays = cal.findall("p:WeekDays/p:WeekDay", ns)
    assert len(weekdays) == 7

    # Monday (DayType 2) should be working with 2 shifts
    monday = next(wd for wd in weekdays if wd.find("p:DayType", ns).text == "2")
    assert monday.find("p:DayWorking", ns).text == "1"
    shifts = monday.findall("p:WorkingTimes/p:WorkingTime", ns)
    assert len(shifts) == 2
    assert shifts[0].find("p:FromTime", ns).text == "08:00:00"
    assert shifts[0].find("p:ToTime", ns).text == "12:00:00"
    assert shifts[1].find("p:FromTime", ns).text == "13:00:00"
    assert shifts[1].find("p:ToTime", ns).text == "17:00:00"

    # Exceptions nested in TimePeriod
    exceptions = cal.findall("p:Exceptions/p:Exception", ns)
    assert len(exceptions) == 2
    for exc in exceptions:
        tp = exc.find("p:TimePeriod", ns)
        assert tp is not None
        assert tp.find("p:FromDate", ns) is not None
        assert tp.find("p:ToDate", ns) is not None
        assert exc.find("p:Occurrences", ns).text == "1"
        assert exc.find("p:DayWorking", ns).text == "0"


def test_resource_types_and_generic_flags(sample_data):
    xml_str = build_ms_project_xml(sample_data["req"], sample_data["calendars"], sample_data["resources"])
    root = ET.fromstring(xml_str)
    ns = {"p": "http://schemas.microsoft.com/project"}

    # Named resource (UID 101)
    named = root.find("p:Resources/p:Resource[p:UID='101']", ns)
    assert named is not None
    assert named.find("p:Type", ns).text == "1"  # Work
    assert named.find("p:IsGeneric", ns).text == "0"
    assert named.find("p:GUID", ns).text == "11111111-2222-3333-4444-555555555555"

    # Generic resource (UID 202)
    generic = root.find("p:Resources/p:Resource[p:UID='202']", ns)
    assert generic is not None
    assert generic.find("p:Type", ns).text == "1"
    assert generic.find("p:IsGeneric", ns).text == "1"

    # Cost resource (UID 404): Must be Type 2, NOT Type 0
    cost_res = root.find("p:Resources/p:Resource[p:UID='404']", ns)
    assert cost_res is not None
    assert cost_res.find("p:Type", ns).text == "2"

    # Inactive resource (UID 303) must NOT appear in new template (soft-delete rule)
    inactive = root.find("p:Resources/p:Resource[p:UID='303']", ns)
    assert inactive is None


def test_rate_tables_chronology_and_indices(sample_data):
    xml_str = build_ms_project_xml(sample_data["req"], sample_data["calendars"], sample_data["resources"])
    root = ET.fromstring(xml_str)
    ns = {"p": "http://schemas.microsoft.com/project"}

    named = root.find("p:Resources/p:Resource[p:UID='101']", ns)
    rates = named.findall("p:Rates/p:Rate", ns)
    assert len(rates) == 3

    # Table A (index 0)
    assert rates[0].find("p:RateTable", ns).text == "0"
    assert rates[0].find("p:StandardRate", ns).text == "45.00"
    assert rates[0].find("p:StandardRateFormat", ns).text == "2"

    # Table B (index 1)
    assert rates[1].find("p:RateTable", ns).text == "1"
    assert rates[1].find("p:StandardRate", ns).text == "55.00"

    # Table C (index 2)
    assert rates[2].find("p:RateTable", ns).text == "2"
    assert rates[2].find("p:StandardRate", ns).text == "75.00"


def test_field_id_calculations():
    # Task Text1
    fid_task_text1, name1 = get_field_id(CustomFieldEntityEnum.TASK, CustomFieldTypeEnum.TEXT, 1)
    assert fid_task_text1 == "188743731"
    assert name1 == "Text1"

    # Resource Text1
    fid_res_text1, name2 = get_field_id(CustomFieldEntityEnum.RESOURCE, CustomFieldTypeEnum.TEXT, 1)
    assert fid_res_text1 == "205520904"
    assert name2 == "Text1"


def test_holiday_service_multi_country():
    countries = get_supported_countries()
    assert "LT" in countries
    assert "NO" in countries

    lt_holidays = fetch_country_holidays("LT", [2026])
    assert len(lt_holidays) > 0
    assert any("Labour" in h["name"] or "Tarptautinė darbo diena" in h["name"] or "Labour Day" in h["name"] for h in lt_holidays)

    no_holidays = fetch_country_holidays("NO", [2026])
    assert len(no_holidays) > 0
    assert any("17" in str(h["from_date"]) for h in no_holidays)
