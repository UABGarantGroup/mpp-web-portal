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

    # Verify all 7 weekdays in Base Calendar 3 are DayWorking = 1 with 13:00-17:00 shift
    cal_el = root.find(".//ms:Calendar[ms:UID='3']", ns)
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


def test_calendar_rename_and_hide(client):
    # 1. Create a new calendar
    create_payload = {
        "name": "Custom Temporary Calendar",
        "description": "To be renamed and hidden",
        "is_active": True,
        "weekdays": [
            {
                "day_type": dt,
                "day_working": dt not in (1, 7),
                "working_times": [
                    {"from_time": "08:00:00", "to_time": "12:00:00"},
                    {"from_time": "13:00:00", "to_time": "17:00:00"}
                ] if dt not in (1, 7) else []
            }
            for dt in range(1, 8)
        ]
    }
    r_create = client.post("/api/calendars", json=create_payload)
    assert r_create.status_code == 201
    created = r_create.json()
    cal_id = created["id"]
    assert created["name"] == "Custom Temporary Calendar"
    assert created["is_active"] is True

    # 2. Rename calendar
    r_rename = client.put(f"/api/calendars/{cal_id}", json={"name": "Renamed Custom Calendar"})
    assert r_rename.status_code == 200
    assert r_rename.json()["name"] == "Renamed Custom Calendar"

    # 3. Hide calendar
    r_hide = client.put(f"/api/calendars/{cal_id}/hide", json={"is_active": False})
    assert r_hide.status_code == 200
    assert r_hide.json()["is_active"] is False

    # Check listing without inactive
    r_active_list = client.get("/api/calendars?include_inactive=false")
    assert r_active_list.status_code == 200
    active_ids = [c["id"] for c in r_active_list.json()]
    assert cal_id not in active_ids

    # Check listing with inactive
    r_all_list = client.get("/api/calendars?include_inactive=true")
    assert r_all_list.status_code == 200
    all_ids = [c["id"] for c in r_all_list.json()]
    assert cal_id in all_ids

    # 4. Unhide calendar
    r_unhide = client.put(f"/api/calendars/{cal_id}/hide", json={"is_active": True})
    assert r_unhide.status_code == 200
    assert r_unhide.json()["is_active"] is True


def test_export_xml_contains_all_active_calendars_and_resources(client):
    # Call export with minimal selected_resource_ids
    template_req = {
        "project_id": 101,
        "project_guid": "multi-cal-res-guid",
        "project_erp_number": "26-8888",
        "project_title": "Enterprise Active Export Test",
        "company_name": "Garant Group",
        "start_date": "2026-06-01",
        "calendar_id": 1,
        "selected_resource_ids": [1],
        "budget_cost": 10000.0,
        "custom_fields": [],
        "project_custom_values": {}
    }
    resp = client.post("/api/templates/export/xml", json=template_req)
    assert resp.status_code == 200

    root = ET.fromstring(resp.text)
    ns = {"ms": "http://schemas.microsoft.com/project"}

    # Get active calendars from API
    active_cals = client.get("/api/calendars?include_inactive=false").json()
    active_cal_names = {c["name"] for c in active_cals}

    exported_base_cal_names = set()
    for cal in root.findall(".//ms:Calendar[ms:IsBaseCalendar='1']", ns):
        name_el = cal.find("ms:Name", ns)
        if name_el is not None:
            exported_base_cal_names.add(name_el.text)

    # All active calendars should be present in exported base calendars
    for ac_name in active_cal_names:
        assert ac_name in exported_base_cal_names

    # Check active resources
    active_resources = client.get("/api/resources").json()
    active_resource_names = {r["name"] for r in active_resources if r.get("is_active", True)}

    exported_res_names = set()
    for res in root.findall(".//ms:Resource", ns):
        name_el = res.find("ms:Name", ns)
        if name_el is not None and name_el.text:
            exported_res_names.add(name_el.text)

    for ar_name in active_resource_names:
        assert ar_name in exported_res_names

