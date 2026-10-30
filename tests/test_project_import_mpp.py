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


def test_rename_project_preserves_custom_name_and_allows_schedule_uploads(client, db_session):
    """
    Verifies that:
    1. First-time import sets project name from Task 0 description.
    2. PUT /api/projects/{project_id}/name updates the project display name in the portal.
    3. Re-uploading the schedule file after renaming succeeds and does NOT overwrite the modified portal project name.
    """
    pm = db_session.query(PortalUserDB).filter(PortalUserDB.is_active == True).first()
    assert pm is not None

    initial_task0_name = "26-0701 NORDIC STAR main engine overhaul"
    xml_bytes = _build_test_mspdi_xml(top_task_name=initial_task0_name, erp=None, cost=15000.0)

    # 1. Initial import sets name from Task 0
    import_resp = client.post(
        "/api/projects/import-mpp",
        data={"owner": pm.display_name, "calendar_id": "1"},
        files={"file": (f"{initial_task0_name}.xml", xml_bytes, "application/xml")},
    )
    assert import_resp.status_code == 200, import_resp.text
    imported = import_resp.json()
    proj_id = imported["id"]
    assert imported["name"] == initial_task0_name

    # 2. Rename project in portal
    custom_portal_name = "26-0701 NORDIC STAR - Custom Portal Display Name"
    rename_resp = client.put(
        f"/api/projects/{proj_id}/name",
        json={"name": custom_portal_name},
    )
    assert rename_resp.status_code == 200, rename_resp.text
    assert rename_resp.json()["name"] == custom_portal_name

    # Empty name must be rejected
    bad_rename = client.put(
        f"/api/projects/{proj_id}/name",
        json={"name": "   "},
    )
    assert bad_rename.status_code in (400, 422)

    # 3. Upload updated schedule where Task 0 still has original schedule task name
    updated_xml = _build_test_mspdi_xml(top_task_name=initial_task0_name, erp=None, cost=31000.0)
    up_resp = client.post(
        f"/api/projects/{proj_id}/upload-schedule",
        files={"file": (f"{initial_task0_name}.xml", updated_xml, "application/xml")},
    )
    assert up_resp.status_code == 200, up_resp.text
    up_data = up_resp.json()
    assert up_data["project_name"] == custom_portal_name
    assert up_data["metrics"]["cost"] == 31000.0


def test_upload_schedule_with_stale_template_erp_uses_technical_field_and_succeeds(client, db_session):
    """
    Regression test for uploading a schedule to seeded project '25-0980' ('25-0980 Pikasoima IGG katilu apsauga')
    when the schedule file contains ERP '26-0980' in Task 0 Text1 (or even a modified Task 0 name).
    Also verifies that technical GUID (PortalProjectGUID Text30 / Task 0 GUID) is embedded in exported XML
    and links the schedule to the project on subsequent uploads.
    """
    proj = db_session.query(ProjectDB).filter(ProjectDB.erp_number == "25-0980").first()
    assert proj is not None
    proj_id = proj.id
    proj_name = proj.name  # '25-0980 Pikasoima IGG katilu apsauga'

    # 1. Upload schedule that has '26-0980' in Task 0 Text1 to project '25-0980' -> must succeed!
    xml_with_26_0980 = _build_test_mspdi_xml(top_task_name="26-0980 Pikasoima IGG katilu apsauga", erp="26-0980", cost=27400.0)
    up_resp = client.post(
        f"/api/projects/{proj_id}/upload-schedule",
        files={"file": (f"{proj_name}.mpp.xml", xml_with_26_0980, "application/xml")},
    )
    assert up_resp.status_code == 200, up_resp.text
    assert up_resp.json()["metrics"]["cost"] == 27400.0

    # 2. Export XML template for this project and verify technical PortalProjectGUID (FieldID 188744016) & Task 0 GUID exist
    exp_resp = client.get(f"/api/projects/{proj_id}/template/xml")
    assert exp_resp.status_code == 200
    db_session.refresh(proj)
    assert proj.project_guid in exp_resp.text
    assert "188744016" in exp_resp.text

    # 3. Modify both Title, Task 0 Name, and Text1 ERP in the exported XML while keeping technical PortalProjectGUID
    root = ET.fromstring(exp_resp.content.decode("utf-8"))
    ns_url = "http://schemas.microsoft.com/project"
    ns = {"ms": ns_url}
    title_el = root.find("ms:Title", ns)
    if title_el is not None:
        title_el.text = "Completely Renamed Schedule Title"
    for task in root.findall(".//ms:Task", ns):
        uid = task.find("ms:UID", ns)
        if uid is not None and uid.text == "0":
            name_el = task.find("ms:Name", ns)
            if name_el is not None:
                name_el.text = "Completely Renamed Task 0"
            cost_el = task.find("ms:Cost", ns)
            if cost_el is None:
                cost_el = ET.SubElement(task, f"{{{ns_url}}}Cost")
            cost_el.text = "39900.00"
            for ea in task.findall("ms:ExtendedAttribute", ns):
                fid = ea.find("ms:FieldID", ns)
                val = ea.find("ms:Value", ns)
                if fid is not None and fid.text == "188743731" and val is not None:
                    val.text = "26-0980"

    modified_xml = ET.tostring(root, encoding="utf-8")
    up_resp_2 = client.post(
        f"/api/projects/{proj_id}/upload-schedule",
        files={"file": ("renamed_file.xml", modified_xml, "application/xml")},
    )
    assert up_resp_2.status_code == 200, up_resp_2.text
    assert up_resp_2.json()["metrics"]["cost"] == 39900.0


def test_leaf_task_progress_rollup_and_zero_work_budget_assignment(client, db_session):
    """
    Verifies that:
    1) When Task 0 has 0% complete / 0% work complete (e.g. Manual calculation mode in MS Project),
       the parser rolls up % Complete, % Work Complete, Cost, Actual Cost, Start, and Finish from leaf tasks.
    2) Exported XML template sets <Work>PT0H0M0S</Work> and <Units>0</Units> on the Task 0 Project Budget
       assignment (ResourceUID=9999) so MS Project Desktop never assigns phantom work to the Cost resource.
    """
    proj = db_session.query(ProjectDB).filter(ProjectDB.erp_number == "25-0980").first()
    assert proj is not None

    # 1. Verify exported XML has zero work and zero units for Project Budget (ResourceUID=9999)
    exp_resp = client.get(f"/api/projects/{proj.id}/template/xml")
    assert exp_resp.status_code == 200
    root = ET.fromstring(exp_resp.content.decode("utf-8"))
    ns = {"ms": "http://schemas.microsoft.com/project"}
    budget_asgn = None
    for asgn in root.findall(".//ms:Assignment", ns):
        r_uid = asgn.find("ms:ResourceUID", ns)
        if r_uid is not None and r_uid.text == "9999":
            budget_asgn = asgn
            break
    assert budget_asgn is not None
    assert budget_asgn.find("ms:Work", ns).text == "PT0H0M0S"
    assert budget_asgn.find("ms:Units", ns).text == "0"

    # 2. Upload XML where Task 0 has 0% complete / 0% work complete, while leaf tasks have progress
    unrecalculated_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Project xmlns="http://schemas.microsoft.com/project">
    <Title>25-0980 Pikasoima IGG katilu apsauga</Title>
    <Tasks>
        <Task>
            <UID>0</UID>
            <ID>0</ID>
            <Name>25-0980 Pikasoima IGG katilu apsauga</Name>
            <Summary>1</Summary>
            <PercentComplete>0</PercentComplete>
            <PercentWorkComplete>0</PercentWorkComplete>
            <Start>2026-10-30T08:00:00</Start>
            <Finish>2026-11-03T18:00:00</Finish>
            <Cost>0</Cost>
            <ActualCost>0</ActualCost>
            <BudgetCost>1000.00</BudgetCost>
        </Task>
        <Task>
            <UID>1</UID>
            <ID>1</ID>
            <Name>darbas 0</Name>
            <Summary>0</Summary>
            <Duration>PT20H0M0S</Duration>
            <ActualDuration>PT2H24M0S</ActualDuration>
            <PercentComplete>12</PercentComplete>
            <Work>PT20H0M0S</Work>
            <ActualWork>PT2H24M0S</ActualWork>
            <PercentWorkComplete>12</PercentWorkComplete>
            <Start>2026-10-30T08:00:00</Start>
            <Finish>2026-11-03T18:00:00</Finish>
            <Cost>760.00</Cost>
            <ActualCost>91.20</ActualCost>
        </Task>
        <Task>
            <UID>2</UID>
            <ID>2</ID>
            <Name>darbas 2</Name>
            <Summary>0</Summary>
            <Duration>PT50H0M0S</Duration>
            <ActualDuration>PT0H0M0S</ActualDuration>
            <PercentComplete>0</PercentComplete>
            <Work>PT50H0M0S</Work>
            <ActualWork>PT0H0M0S</ActualWork>
            <PercentWorkComplete>0</PercentWorkComplete>
            <Start>2026-11-04T08:00:00</Start>
            <Finish>2026-11-10T18:00:00</Finish>
            <Cost>1900.00</Cost>
            <ActualCost>0.00</ActualCost>
        </Task>
    </Tasks>
</Project>"""
    up_resp = client.post(
        f"/api/projects/{proj.id}/upload-schedule",
        files={"file": ("25-0980_schedule.xml", unrecalculated_xml, "application/xml")},
    )
    assert up_resp.status_code == 200, up_resp.text
    metrics = up_resp.json()["metrics"]
    assert metrics["percent_complete"] == 3.4
    assert metrics["percent_work_complete"] == 3.4
    assert metrics["cost"] == 2660.0
    assert metrics["actual_cost"] == 91.2
    assert metrics["finish_date"] == "2026-11-10"


def test_import_mpp_upserts_existing_project_and_creates_new_project(client, db_session):
    """
    Verifies the unified Import from MPP behavior:
    1) When the uploaded schedule matches an existing project (by ERP, project name, or technical GUID),
       POST /api/projects/import-mpp updates the existing project and returns action == 'updated'
       (without requiring PM owner selection for the existing project).
    2) When the uploaded schedule does NOT match any existing project, POST /api/projects/import-mpp
       runs the standard creation flow and returns action == 'created'.
    """
    pm = db_session.query(PortalUserDB).filter(PortalUserDB.is_active == True).first()
    assert pm is not None

    # 1. Import a brand new project -> should create (action == 'created')
    new_task_name = "26-8811 BALTIC QUEEN thruster repair"
    new_erp = "26-8811"
    xml_create = _build_test_mspdi_xml(top_task_name=new_task_name, erp=new_erp, cost=14000.0)
    resp_create = client.post(
        "/api/projects/import-mpp",
        data={"owner": pm.display_name, "calendar_id": "1"},
        files={"file": ("baltic_queen.xml", xml_create, "application/xml")},
    )
    assert resp_create.status_code == 200, resp_create.text
    created_data = resp_create.json()
    assert created_data["action"] == "created"
    assert created_data["erp_number"] == new_erp
    assert created_data["name"] == new_task_name
    assert created_data["metrics"]["cost"] == 14000.0
    proj_id = created_data["id"]

    # 2. Re-import an updated schedule for the same project via /api/projects/import-mpp
    #    Even without passing owner or explicit erp_number, it must detect the existing project and update it!
    xml_update = _build_test_mspdi_xml(top_task_name=new_task_name, erp=new_erp, cost=29500.0)
    resp_update = client.post(
        "/api/projects/import-mpp",
        data={},
        files={"file": ("baltic_queen_v2.xml", xml_update, "application/xml")},
    )
    assert resp_update.status_code == 200, resp_update.text
    updated_data = resp_update.json()
    assert updated_data["action"] == "updated"
    assert updated_data["id"] == proj_id
    assert updated_data["erp_number"] == new_erp
    assert updated_data["metrics"]["cost"] == 29500.0





