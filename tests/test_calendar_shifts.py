"""
Tests for Granular Calendar Working Hours and Weekday Shifts:
- Weekly schedule configuration (Monday to Sunday)
- Specific shift hours (e.g. Mon-Sun 13:00-17:00, 4h/day)
- Dynamic MS Project XML header metric calculation (MinutesPerDay, MinutesPerWeek, DefaultStartTime/FinishTime)
- Full WeekDays and WorkingTimes generation in exported MSPDI XML
"""

import xml.etree.ElementTree as ET
import pytest
from backend.app.models.schemas import (
    CalendarModel,
    CostRateItem,
    ProjectTemplateRequest,
    ResourceModel,
    WeekDayModel,
    WorkingShiftModel,
)
from backend.app.services.xml_generator import build_ms_project_xml, compute_calendar_metrics
from datetime import date


def test_compute_calendar_metrics_standard():
    # 5 days (Mon-Fri) 8h = 40h/week
    weekdays = []
    for day_type in range(1, 8):
        is_working = day_type not in (1, 7)
        shifts = []
        if is_working:
            shifts = [
                WorkingShiftModel(from_time="08:00:00", to_time="12:00:00"),
                WorkingShiftModel(from_time="13:00:00", to_time="17:00:00"),
            ]
        weekdays.append(WeekDayModel(day_type=day_type, day_working=is_working, working_times=shifts))

    cal = CalendarModel(id=1, name="Standard", country_code="LT", weekdays=weekdays)
    def_start, def_finish, mins_day, mins_week, days_month = compute_calendar_metrics(cal)

    assert def_start == "08:00:00"
    assert def_finish == "17:00:00"
    assert mins_day == 480  # 8 hours
    assert mins_week == 2400  # 40 hours
    assert days_month == 22 or days_month == 20


def test_compute_calendar_metrics_mon_sun_4h():
    # Monday to Sunday 4h (13:00-17:00) = 28h/week
    weekdays = []
    for day_type in range(1, 8):
        shifts = [WorkingShiftModel(from_time="13:00:00", to_time="17:00:00")]
        weekdays.append(WeekDayModel(day_type=day_type, day_working=True, working_times=shifts))

    cal = CalendarModel(id=3, name="Afternoon 28h", country_code="LT", weekdays=weekdays)
    def_start, def_finish, mins_day, mins_week, days_month = compute_calendar_metrics(cal)

    assert def_start == "13:00:00"
    assert def_finish == "17:00:00"
    assert mins_day == 240  # 4 hours
    assert mins_week == 1680  # 28 hours (7 * 4 * 60)
    assert days_month == 30  # 7 * 4.33 ≈ 30


def test_api_calendars_includes_weekdays(client):
    resp = client.get("/api/calendars")
    assert resp.status_code == 200
    calendars = resp.json()
    assert len(calendars) >= 3

    # Check Afternoon Shift Calendar (ID 3)
    cal_3 = next((c for c in calendars if c["id"] == 3), None)
    assert cal_3 is not None
    assert "13:00-17:00" in cal_3["name"]
    assert len(cal_3["weekdays"]) == 7

    for wd in cal_3["weekdays"]:
        assert wd["day_working"] is True
        assert len(wd["working_times"]) == 1
        assert wd["working_times"][0]["from_time"] == "13:00:00"
        assert wd["working_times"][0]["to_time"] == "17:00:00"


def test_admin_update_calendar_weekdays(client):
    # Admin can update weekdays
    custom_weekdays = {
        "weekdays": [
            {
                "day_type": 1,  # Sunday non-working
                "day_working": False,
                "working_times": []
            },
            {
                "day_type": 2,  # Monday 6 hours (09:00-15:00)
                "day_working": True,
                "working_times": [{"from_time": "09:00:00", "to_time": "15:00:00"}]
            },
            {
                "day_type": 3,  # Tuesday 6 hours
                "day_working": True,
                "working_times": [{"from_time": "09:00:00", "to_time": "15:00:00"}]
            },
            {
                "day_type": 4,  # Wednesday 6 hours
                "day_working": True,
                "working_times": [{"from_time": "09:00:00", "to_time": "15:00:00"}]
            },
            {
                "day_type": 5,  # Thursday 6 hours
                "day_working": True,
                "working_times": [{"from_time": "09:00:00", "to_time": "15:00:00"}]
            },
            {
                "day_type": 6,  # Friday 4 hours (09:00-13:00)
                "day_working": True,
                "working_times": [{"from_time": "09:00:00", "to_time": "13:00:00"}]
            },
            {
                "day_type": 7,  # Saturday non-working
                "day_working": False,
                "working_times": []
            }
        ]
    }

    # PM cannot update weekdays
    resp_pm = client.put(
        "/api/calendars/1/weekdays",
        json=custom_weekdays,
        headers={"X-User-Role": "PM", "X-User-Email": "pm@garant.eu"}
    )
    assert resp_pm.status_code == 403

    # Admin updates weekdays
    resp_admin = client.put(
        "/api/calendars/1/weekdays",
        json=custom_weekdays,
        headers={"X-User-Role": "Admin", "X-User-Email": "admin@garant.eu"}
    )
    assert resp_admin.status_code == 200
    updated_cal = resp_admin.json()
    assert len(updated_cal["weekdays"]) == 7
    friday = next(w for w in updated_cal["weekdays"] if w["day_type"] == 6)
    assert friday["day_working"] is True
    assert friday["working_times"][0]["to_time"] == "13:00:00"


def test_export_xml_with_afternoon_calendar_mon_sun_4h(client):
    # Create template request with calendar 3 (Mon-Sun 13:00-17:00)
    template_req = {
        "project_id": 99,
        "project_guid": "afternoon-test-guid",
        "project_erp_number": "26-7777",
        "project_title": "Afternoon Shift Vessel Repair",
        "company_name": "Garant Group",
        "start_date": "2026-07-01",
        "calendar_id": 3,
        "selected_resource_ids": [1],
        "budget_cost": 25000.0,
        "custom_fields": [],
        "project_custom_values": {}
    }

    resp = client.post("/api/templates/export/xml", json=template_req)
    assert resp.status_code == 200
    xml_text = resp.text

    root = ET.fromstring(xml_text)
    ns = {"ms": "http://schemas.microsoft.com/project"}

    # Verify project headers derived from calendar 3
    start_time_el = root.find("ms:DefaultStartTime", ns)
    finish_time_el = root.find("ms:DefaultFinishTime", ns)
    mins_day_el = root.find("ms:MinutesPerDay", ns)
    mins_week_el = root.find("ms:MinutesPerWeek", ns)

    assert start_time_el is not None and start_time_el.text == "13:00:00"
    assert finish_time_el is not None and finish_time_el.text == "17:00:00"
    assert mins_day_el is not None and mins_day_el.text == "240"
    assert mins_week_el is not None and mins_week_el.text == "1680"

    # Verify Task 0 starts at 13:00:00 and finishes at 17:00:00
    task_0 = None
    for task in root.findall(".//ms:Task", ns):
        uid = task.find("ms:UID", ns)
        if uid is not None and uid.text == "0":
            task_0 = task
            break
    assert task_0 is not None
    assert "T13:00:00" in task_0.find("ms:Start", ns).text
    assert "T17:00:00" in task_0.find("ms:Finish", ns).text

    # Verify all 7 weekdays in Base Calendar are DayWorking = 1 with 13:00-17:00 shift
    cal_el = root.find(".//ms:Calendar[ms:IsBaseCalendar='1']", ns)
    assert cal_el is not None

    weekdays_el = cal_el.find("ms:WeekDays", ns)
    assert weekdays_el is not None
    weekdays = weekdays_el.findall("ms:WeekDay", ns)
    assert len(weekdays) == 7

    for wd in weekdays:
        assert wd.find("ms:DayWorking", ns).text == "1"
        wtimes = wd.find("ms:WorkingTimes", ns)
        assert wtimes is not None
        wt = wtimes.find("ms:WorkingTime", ns)
        assert wt is not None
        assert wt.find("ms:FromTime", ns).text == "13:00:00"
        assert wt.find("ms:ToTime", ns).text == "17:00:00"
