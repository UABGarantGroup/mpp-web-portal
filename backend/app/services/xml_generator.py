"""
Robust, standards-compliant Microsoft Project XML (MSPDI) Generator.
Conforms strictly to Microsoft Project XML Data Interchange Schema (http://schemas.microsoft.com/project).
Addresses all architectural constraints:
- Stable resource UIDs & GUIDs
- Correct Resource Type (Work=1, Material=0, Cost=2)
- Rate Tables A-E with chronological ordering and dated periods
- Valid Base Calendar with WeekDays working hours
- Calendar exceptions nested inside <TimePeriod>
- Dedicated Budget Resource (<Type>2</Type>, <IsBudget>1</IsBudget>) assigned to Task 0 via <BudgetCost>
- Proper ExtendedAttribute FieldIDs for Task, Resource, and Project entities
- Correct canonical top-level XML element sequence
"""

from datetime import date, datetime, time
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET
from xml.dom import minidom

from backend.app.models.enums import (
    CustomFieldEntityEnum,
    CustomFieldTypeEnum,
    RateTableEnum,
    ResourceTypeEnum,
)
from backend.app.models.schemas import (
    CalendarModel,
    CustomFieldDefinition,
    ProjectTemplateRequest,
    ResourceModel,
)
from backend.app.services.field_ids import get_field_id

# Rate table mapping: A -> 0, B -> 1, C -> 2, D -> 3, E -> 4
RATE_TABLE_MAP: Dict[RateTableEnum, int] = {
    RateTableEnum.A: 0,
    RateTableEnum.B: 1,
    RateTableEnum.C: 2,
    RateTableEnum.D: 3,
    RateTableEnum.E: 4,
}

# Resource type mapping: Material -> 0, Work -> 1, Cost -> 2
RESOURCE_TYPE_MAP: Dict[ResourceTypeEnum, int] = {
    ResourceTypeEnum.MATERIAL: 0,
    ResourceTypeEnum.WORK: 1,
    ResourceTypeEnum.COST: 2,
}


def build_ms_project_xml(
    template_req: ProjectTemplateRequest,
    calendars: Dict[int, CalendarModel],
    resources: Dict[int, ResourceModel],
) -> str:
    """
    Builds a fully compliant MS Project XML document.
    """
    ns = "http://schemas.microsoft.com/project"
    root = ET.Element("Project", xmlns=ns)

    # 1. Project Header Elements (Strict Canonical Sequence)
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    start_iso = f"{template_req.start_date.isoformat()}T08:00:00"

    ET.SubElement(root, "SaveVersion").text = "14"  # Project 2010/2013/2016/2019/M365
    ET.SubElement(root, "Name").text = template_req.project_title
    ET.SubElement(root, "Title").text = template_req.project_title
    ET.SubElement(root, "Company").text = template_req.company_name or "Enterprise Global"
    ET.SubElement(root, "Author").text = "MS Project Centralized Resource Hub"
    ET.SubElement(root, "CreationDate").text = now_iso
    ET.SubElement(root, "LastSaved").text = now_iso
    ET.SubElement(root, "ScheduleFromStart").text = "1"
    ET.SubElement(root, "StartDate").text = start_iso
    ET.SubElement(root, "FinishDate").text = start_iso
    ET.SubElement(root, "FYStartDate").text = "1"
    ET.SubElement(root, "CriticalSlackLimit").text = "0"
    ET.SubElement(root, "CurrencyDigits").text = "2"
    ET.SubElement(root, "CurrencySymbol").text = "€"
    ET.SubElement(root, "CurrencyCode").text = "EUR"
    ET.SubElement(root, "CurrencySymbolPosition").text = "3"  # e.g., 100 €
    ET.SubElement(root, "CalendarUID").text = str(template_req.calendar_id)
    ET.SubElement(root, "DefaultStartTime").text = "08:00:00"
    ET.SubElement(root, "DefaultFinishTime").text = "17:00:00"
    ET.SubElement(root, "MinutesPerDay").text = "480"
    ET.SubElement(root, "MinutesPerWeek").text = "2400"
    ET.SubElement(root, "DaysPerMonth").text = "20"
    ET.SubElement(root, "DefaultTaskType").text = "0"
    ET.SubElement(root, "DefaultFixedCostAccrual").text = "3"
    ET.SubElement(root, "DefaultStandardRate").text = "0"
    ET.SubElement(root, "DefaultOvertimeRate").text = "0"
    ET.SubElement(root, "DurationFormat").text = "7"  # Days
    ET.SubElement(root, "WorkFormat").text = "2"      # Hours
    ET.SubElement(root, "EditableActualCosts").text = "0"
    ET.SubElement(root, "HonorConstraints").text = "0"
    ET.SubElement(root, "InsertedProjectsLikeSummary").text = "1"
    ET.SubElement(root, "MultipleCriticalPaths").text = "0"
    ET.SubElement(root, "NewTasksEffortDriven").text = "1"
    ET.SubElement(root, "NewTasksEstimated").text = "1"
    ET.SubElement(root, "SplitsInProgressTasks").text = "1"
    ET.SubElement(root, "SpreadActualCost").text = "0"
    ET.SubElement(root, "SpreadPercentComplete").text = "0"
    ET.SubElement(root, "TaskUpdatesResource").text = "1"
    ET.SubElement(root, "FiscalYearStart").text = "0"
    ET.SubElement(root, "WeekStartDay").text = "1"  # Monday = 1
    ET.SubElement(root, "MoveCompletedEndsBack").text = "0"
    ET.SubElement(root, "MoveRemainingStartsBack").text = "0"
    ET.SubElement(root, "MoveRemainingStartsForward").text = "0"
    ET.SubElement(root, "MoveCompletedEndsForward").text = "0"
    ET.SubElement(root, "BaselineForEarnedValue").text = "0"
    ET.SubElement(root, "AutoAddNewResourcesAndTasks").text = "1"

    # 2. Extended Attributes (Custom Field Definitions)
    ext_attrs_el = ET.SubElement(root, "ExtendedAttributes")
    for cf in template_req.custom_fields:
        field_id = cf.field_id
        field_name = cf.field_name
        if not field_id:
            field_id, internal_name = get_field_id(cf.entity, cf.field_type, cf.slot_number)
            if not field_name:
                field_name = internal_name

        ext_attr = ET.SubElement(ext_attrs_el, "ExtendedAttribute")
        ET.SubElement(ext_attr, "FieldID").text = str(field_id)
        ET.SubElement(ext_attr, "FieldName").text = field_name
        ET.SubElement(ext_attr, "Alias").text = cf.alias or field_name

    # 3. Calendars Definition
    calendars_el = ET.SubElement(root, "Calendars")
    selected_cal = calendars.get(template_req.calendar_id)
    if not selected_cal:
        selected_cal = list(calendars.values())[0] if calendars else CalendarModel(
            id=1, name="Standard Enterprise Calendar"
        )

    # Write Base Calendar
    cal_el = ET.SubElement(calendars_el, "Calendar")
    ET.SubElement(cal_el, "UID").text = str(selected_cal.id)
    ET.SubElement(cal_el, "Name").text = selected_cal.name
    ET.SubElement(cal_el, "IsBaseCalendar").text = "1"
    ET.SubElement(cal_el, "BaseCalendarUID").text = "-1"

    # Write WeekDays with standard working hours (Mon-Fri 08:00-12:00, 13:00-17:00)
    weekdays_el = ET.SubElement(cal_el, "WeekDays")
    for day_type in range(1, 8):  # 1=Sunday, 2=Monday, ..., 7=Saturday
        wd_el = ET.SubElement(weekdays_el, "WeekDay")
        ET.SubElement(wd_el, "DayType").text = str(day_type)
        if day_type in (1, 7):  # Weekend
            ET.SubElement(wd_el, "DayWorking").text = "0"
        else:  # Working day
            ET.SubElement(wd_el, "DayWorking").text = "1"
            wtimes_el = ET.SubElement(wd_el, "WorkingTimes")
            # Shift 1: 08:00 to 12:00
            wt1 = ET.SubElement(wtimes_el, "WorkingTime")
            ET.SubElement(wt1, "FromTime").text = "08:00:00"
            ET.SubElement(wt1, "ToTime").text = "12:00:00"
            # Shift 2: 13:00 to 17:00
            wt2 = ET.SubElement(wtimes_el, "WorkingTime")
            ET.SubElement(wt2, "FromTime").text = "13:00:00"
            ET.SubElement(wt2, "ToTime").text = "17:00:00"

    # Write Exceptions nested inside <TimePeriod>
    if selected_cal.exceptions:
        exceptions_el = ET.SubElement(cal_el, "Exceptions")
        # Sort exceptions chronologically
        sorted_exceptions = sorted(selected_cal.exceptions, key=lambda x: x.from_date)
        for exc in sorted_exceptions:
            exc_el = ET.SubElement(exceptions_el, "Exception")
            ET.SubElement(exc_el, "EnteredByOccurrences").text = "0"

            tp_el = ET.SubElement(exc_el, "TimePeriod")
            ET.SubElement(tp_el, "FromDate").text = f"{exc.from_date.isoformat()}T00:00:00"
            ET.SubElement(tp_el, "ToDate").text = f"{exc.to_date.isoformat()}T23:59:59"

            ET.SubElement(exc_el, "Occurrences").text = "1"
            ET.SubElement(exc_el, "Name").text = exc.name
            ET.SubElement(exc_el, "Type").text = "1"
            ET.SubElement(exc_el, "DayWorking").text = "1" if exc.working else "0"

    # Write Resource-Specific Derived Calendars
    for res_id in template_req.selected_resource_ids:
        res = resources.get(res_id)
        if not res or not res.is_active:
            continue
        res_cal_el = ET.SubElement(calendars_el, "Calendar")
        res_cal_uid = 1000 + res.id
        ET.SubElement(res_cal_el, "UID").text = str(res_cal_uid)
        ET.SubElement(res_cal_el, "Name").text = res.name
        ET.SubElement(res_cal_el, "IsBaseCalendar").text = "0"
        ET.SubElement(res_cal_el, "BaseCalendarUID").text = str(selected_cal.id)

    # 4. Tasks (Project Summary Task UID 0)
    tasks_el = ET.SubElement(root, "Tasks")
    summary_task = ET.SubElement(tasks_el, "Task")
    ET.SubElement(summary_task, "UID").text = "0"
    ET.SubElement(summary_task, "ID").text = "0"
    ET.SubElement(summary_task, "Type").text = "1"
    ET.SubElement(summary_task, "IsNull").text = "0"
    ET.SubElement(summary_task, "CreateDate").text = now_iso
    ET.SubElement(summary_task, "Name").text = template_req.project_title
    ET.SubElement(summary_task, "WBS").text = "0"
    ET.SubElement(summary_task, "OutlineNumber").text = "0"
    ET.SubElement(summary_task, "OutlineLevel").text = "0"
    ET.SubElement(summary_task, "Priority").text = "500"
    ET.SubElement(summary_task, "Start").text = start_iso
    ET.SubElement(summary_task, "Finish").text = f"{template_req.start_date.isoformat()}T17:00:00"
    ET.SubElement(summary_task, "Duration").text = "PT0H0M0S"
    ET.SubElement(summary_task, "DurationFormat").text = "53"
    ET.SubElement(summary_task, "Work").text = "PT0H0M0S"
    ET.SubElement(summary_task, "Summary").text = "1"
    ET.SubElement(summary_task, "Critical").text = "1"

    # Custom field values on Project Summary Task (Project-level metadata)
    for field_name, field_val in template_req.project_custom_values.items():
        # Match with custom field definition
        matched_cf = next((cf for cf in template_req.custom_fields if cf.field_name == field_name or cf.alias == field_name), None)
        if matched_cf:
            f_id = matched_cf.field_id or get_field_id(matched_cf.entity, matched_cf.field_type, matched_cf.slot_number)[0]
            task_ext = ET.SubElement(summary_task, "ExtendedAttribute")
            ET.SubElement(task_ext, "FieldID").text = str(f_id)
            ET.SubElement(task_ext, "Value").text = str(field_val)

    # 5. Resources Section
    resources_el = ET.SubElement(root, "Resources")

    # Standard Null Resource (UID 0)
    null_res = ET.SubElement(resources_el, "Resource")
    ET.SubElement(null_res, "UID").text = "0"
    ET.SubElement(null_res, "ID").text = "0"
    ET.SubElement(null_res, "Type").text = "1"
    ET.SubElement(null_res, "IsNull").text = "0"

    # Budget Resource if budget is specified
    budget_resource_uid = 9999
    has_budget = template_req.budget_cost is not None and template_req.budget_cost > 0
    if has_budget:
        b_res = ET.SubElement(resources_el, "Resource")
        ET.SubElement(b_res, "UID").text = str(budget_resource_uid)
        ET.SubElement(b_res, "ID").text = str(budget_resource_uid)
        ET.SubElement(b_res, "Name").text = "Project Budget"
        ET.SubElement(b_res, "Type").text = "2"  # Cost resource
        ET.SubElement(b_res, "IsNull").text = "0"
        ET.SubElement(b_res, "CalendarUID").text = str(selected_cal.id)
        ET.SubElement(b_res, "IsCostResource").text = "1"
        ET.SubElement(b_res, "IsBudget").text = "1"
        ET.SubElement(b_res, "IsGeneric").text = "0"
        ET.SubElement(b_res, "IsInactive").text = "0"

    # Enterprise Resources
    for res_id in template_req.selected_resource_ids:
        res = resources.get(res_id)
        if not res:
            continue
        if not res.is_active:
            # Soft delete rule: exclude inactive resources from NEW templates
            continue

        res_el = ET.SubElement(resources_el, "Resource")
        # Stable UID and ID
        ET.SubElement(res_el, "UID").text = str(res.id)
        ET.SubElement(res_el, "ID").text = str(res.id)
        ET.SubElement(res_el, "GUID").text = res.guid
        ET.SubElement(res_el, "Name").text = res.name
        
        # Resource Type: 0=Material, 1=Work, 2=Cost
        res_type_num = RESOURCE_TYPE_MAP.get(res.resource_type, 1)
        ET.SubElement(res_el, "Type").text = str(res_type_num)
        ET.SubElement(res_el, "IsNull").text = "0"

        if res.email:
            ET.SubElement(res_el, "EmailAddress").text = res.email
        if res.department:
            ET.SubElement(res_el, "Group").text = res.department

        # Calendar UID (Resource derived calendar)
        res_cal_uid = 1000 + res.id
        ET.SubElement(res_el, "CalendarUID").text = str(res_cal_uid)

        # Generic Flag (IsGeneric)
        ET.SubElement(res_el, "IsGeneric").text = "1" if res.is_generic else "0"
        ET.SubElement(res_el, "IsInactive").text = "0" if res.is_active else "1"

        # Extended Attributes on Resource (e.g. Cost Center)
        for field_name, field_val in res.custom_field_values.items():
            matched_cf = next((cf for cf in template_req.custom_fields if cf.field_name == field_name or cf.alias == field_name), None)
            if matched_cf:
                f_id = matched_cf.field_id or get_field_id(matched_cf.entity, matched_cf.field_type, matched_cf.slot_number)[0]
                res_ext = ET.SubElement(res_el, "ExtendedAttribute")
                ET.SubElement(res_ext, "FieldID").text = str(f_id)
                ET.SubElement(res_ext, "Value").text = str(field_val)

        # Cost Rate Tables A-E (Rates strictly sorted chronologically)
        if res.rates:
            rates_el = ET.SubElement(res_el, "Rates")
            # Sort rates strictly chronologically by effective_date
            sorted_rates = sorted(res.rates, key=lambda r: (r.effective_date or date.min, RATE_TABLE_MAP.get(r.rate_table, 0)))

            for rate in sorted_rates:
                rate_entry = ET.SubElement(rates_el, "Rate")
                rate_table_idx = RATE_TABLE_MAP.get(rate.rate_table, 0)

                effective_from = rate.effective_date or template_req.start_date
                rates_to = rate.rates_to or date(2049, 12, 31)

                ET.SubElement(rate_entry, "RatesFrom").text = f"{effective_from.isoformat()}T00:00:00"
                ET.SubElement(rate_entry, "RatesTo").text = f"{rates_to.isoformat()}T23:59:59"
                ET.SubElement(rate_entry, "RateTable").text = str(rate_table_idx)
                ET.SubElement(rate_entry, "StandardRate").text = f"{rate.standard_rate:.2f}"
                ET.SubElement(rate_entry, "StandardRateFormat").text = "2"  # Per hour
                ET.SubElement(rate_entry, "OvertimeRate").text = f"{rate.overtime_rate:.2f}"
                ET.SubElement(rate_entry, "OvertimeRateFormat").text = "2"
                ET.SubElement(rate_entry, "CostPerUse").text = f"{rate.cost_per_use:.2f}"

    # 6. Assignments Section (Budget assignment to Task 0)
    assignments_el = ET.SubElement(root, "Assignments")
    if has_budget:
        budget_assignment = ET.SubElement(assignments_el, "Assignment")
        ET.SubElement(budget_assignment, "UID").text = "1"
        ET.SubElement(budget_assignment, "TaskUID").text = "0"
        ET.SubElement(budget_assignment, "ResourceUID").text = str(budget_resource_uid)
        ET.SubElement(budget_assignment, "BudgetCost").text = f"{template_req.budget_cost:.2f}"

    # Prettify and serialize XML output
    rough_string = ET.tostring(root, encoding="utf-8")
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")
