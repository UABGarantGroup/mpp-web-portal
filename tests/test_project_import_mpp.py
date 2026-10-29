"""
Tests for importing new projects directly from MPP/MSPDI XML schedules with PM assignment:
- Validates PM assignment from portal users list before import.
- Validates top task description is extracted and used as project name.
- Validates ERP code resolution (explicit, file-extracted, or auto-generated).
- Validates initial project snapshot and stage statuses creation.
"""

import io
import xml.etree.ElementTree as ET
import pytest
from datetime import date
from backend.app.db.models import PortalUserDB, ProjectDB


def _build_test_mspdi_xml(top_task_name="Top Task Engine Overhaul Description", erp="26-9999", cost=15000.0):
    ns_url = "http://schemas.microsoft.com/project"
    root = ET.Element(f"{{{ns_url}}}Project")
    
    title_el = ET.SubElement(root, f"{{{ns_url}}}Title")
    title_el.text = "File Title Property"

    tasks_el = ET.SubElement(root, f"{{{ns_url}}}Tasks")
    
    # Task 0 (Project Summary Task)
    task_0 = ET.SubElement(tasks_el, f"{{{ns_url}}}Task")
    uid_el = ET.SubElement(task_0, f"{{{ns_url}}}UID")
    uid_el.text = "0"
    id_el = ET.SubElement(task_0, f"{{{ns_url}}}ID")
    id_el.text = "0"
    name_el = ET.SubElement(task_0, f"{{{ns_url}}}Name")
    name_el.text = top_task_name
    pct_el = ET.SubElement(task_0, f"{{{ns_url}}}PercentComplete")
    pct_el.text = "35"
    pct_work_el = ET.SubElement(task_0, f"{{{ns_url}}}PercentWorkComplete")
    pct_work_el.text = "40"
    cost_el = ET.SubElement(task_0, f"{{{ns_url}}}Cost")
    cost_el.text = str(cost)
    start_el = ET.SubElement(task_0, f"{{{ns_url}}}Start")
    start_el.text = "2026-06-01T08:00:00"
    finish_el = ET.SubElement(task_0, f"{{{ns_url}}}Finish")
    finish_el.text = "2026-08-31T17:00:00"

    # Text1 for ERP
    if erp:
        t1_el = ET.SubElement(task_0, f"{{{ns_url}}}Text1")
        t1_el.text = erp

    return ET.tostring(root, encoding="utf-8")


def test_import_mpp_rejects_missing_or_invalid_pm(client):
    """Import must require a valid Project Manager from portal users list."""
    xml_bytes = _build_test_mspdi_xml()
    files = {"file": ("schedule.xml", xml_bytes, "application/xml")}

    # Missing PM
    r_no_pm = client.post("/api/projects/import-mpp", data={"owner": ""}, files=files)
    assert r_no_pm.status_code == 400
    assert "Project Manager" in r_no_pm.json()["detail"]

    # Invalid PM
    r_bad_pm = client.post(
        "/api/projects/import-mpp",
        data={"owner": "NonExistentUser12345"},
        files=files
    )
    assert r_bad_pm.status_code == 400
    assert "not found" in r_bad_pm.json()["detail"]


def test_import_mpp_success_uses_top_task_description_and_assigns_pm(client, db_session):
    """
    Verifies that importing an MPP file:
    1. Extracts top TASK description and sets it as the project name.
    2. Assigns the selected PM as project owner.
    3. Initializes snapshot metrics and stage statuses.
    """
    # Ensure a portal PM user exists
    pm = db_session.query(PortalUserDB).filter(PortalUserDB.role == "PM").first()
    if not pm:
        pm = PortalUserDB(
            email="test_pm_import@garant.lt",
            display_name="Arturas PM",
            role="PM",
            source="LOCAL",
            is_active=True
        )
        db_session.add(pm)
        db_session.commit()
        db_session.refresh(pm)

    top_task_description = "Dry Dock Hull Blasting & Coating 2026"
    test_erp = "26-7788"
    xml_bytes = _build_test_mspdi_xml(top_task_name=top_task_description, erp=test_erp, cost=18500.0)

    files = {"file": ("drydock_schedule.xml", xml_bytes, "application/xml")}
    data = {
        "owner": pm.display_name,
        "erp_number": test_erp,
        "calendar_id": "1",
    }

    resp = client.post("/api/projects/import-mpp", data=data, files=files)
    assert resp.status_code == 200, resp.text
    res_data = resp.json()

    # Verify project name matches the TOP TASK DESCRIPTION
    assert res_data["name"] == top_task_description
    assert res_data["owner"] == pm.display_name
    assert res_data["erp_number"] == test_erp

    # Verify project persisted in database
    proj_in_db = db_session.query(ProjectDB).filter(ProjectDB.erp_number == test_erp).first()
    assert proj_in_db is not None
    assert proj_in_db.name == top_task_description
    assert proj_in_db.owner == pm.display_name

    # Verify snapshot
    snapshots = proj_in_db.snapshots
    assert len(snapshots) >= 1
    init_snap = snapshots[0]
    assert init_snap.percent_complete == 35.0
    assert init_snap.cost == 18500.0
    assert init_snap.source == "MPP_IMPORT"

    # Verify project is visible in portfolio
    port_resp = client.get("/api/portfolio")
    assert port_resp.status_code == 200
    all_projects = []
    for g in port_resp.json().get("groups", []):
        all_projects.extend(g.get("projects", []))
    matching = [p for p in all_projects if p["erp_number"] == test_erp]
    assert len(matching) == 1
    assert matching[0]["name"] == top_task_description
    assert matching[0]["owner"] == pm.display_name


def test_mpxj_jvm_discovery_and_initialization():
    """
    Verifies that _find_jvm_path locates a valid JVM library,
    and _init_mpxj() starts the JVM cleanly without raising unhandled errors.
    """
    import os
    from backend.app.services.mpxj_parser import _find_jvm_path, _init_mpxj

    jvm_path = _find_jvm_path()
    # If a JVM is present on the environment (e.g., local dev or docker), ensure it exists
    if jvm_path:
        assert os.path.exists(jvm_path)
        assert os.path.isfile(jvm_path)
        # Verify MPXJ initializes successfully with the discovered JVM
        init_ok = _init_mpxj()
        assert init_ok is True


def test_update_existing_imported_project_with_auto_erp_succeeds(client, db_session):
    """
    Regression test for updating an existing project that was imported from MPP
    with an auto-generated ERP code (e.g. 'PRJ-2026-6F5AF1') and top task title
    ('26-0608 STI MILLENIA MAN B&W 6G50ME cylinder heads recon').
    """
    pm = db_session.query(PortalUserDB).filter(PortalUserDB.is_active == True).first()
    assert pm is not None

    task_title = "26-0608 STI MILLENIA MAN B&W 6G50ME cylinder heads recon"
    xml_bytes = _build_test_mspdi_xml(top_task_name=task_title, erp=None, cost=12000.0)

    # 1. Import project without explicit ERP -> generates PRJ-YYYY-XXXXXX
    import_resp = client.post(
        "/api/projects/import-mpp",
        data={"owner": pm.display_name, "calendar_id": "1"},
        files={"file": (f"{task_title}.xml", xml_bytes, "application/xml")},
    )
    assert import_resp.status_code == 200, import_resp.text
    imported = import_resp.json()
    assert imported["erp_number"].startswith("PRJ-")
    assert imported["name"] == task_title
    proj_id = imported["id"]

    # 2. Upload updated schedule file for this existing project
    updated_xml = _build_test_mspdi_xml(top_task_name=task_title, erp=None, cost=24500.0)
    up_resp = client.post(
        f"/api/projects/{proj_id}/upload-schedule",
        files={"file": (f"{task_title}.xml", updated_xml, "application/xml")},
    )
    assert up_resp.status_code == 200, up_resp.text
    up_data = up_resp.json()
    assert up_data["metrics"]["cost"] == 24500.0


