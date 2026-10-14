"""
Tests for Phase 4: Project Schedule Upload (.mpp/.xml), MPXJ parsing,
portfolio snapshot synchronization, and generic resource replacement wizard.
"""

import io
import pytest
import xml.etree.ElementTree as ET
from datetime import date
from starlette.testclient import TestClient

from backend.app.services.mpxj_parser import parse_project_file


def test_mpxj_and_xml_parser_extracts_metrics(client):
    # 1. Download sample XML template for project 1
    resp = client.get("/api/projects/1/template/xml")
    assert resp.status_code == 200
    xml_content = resp.content

    # 2. Parse using parse_project_file
    parsed = parse_project_file(xml_content, "test_project.xml")
    assert parsed["erp_number"] == "26-0537"
    assert parsed["percent_complete"] == 0.0
    assert parsed["budget_cost"] > 0
    assert "start_date" in parsed
    assert len(parsed["resources"]) > 0

    # Ensure generic placeholder is flagged properly
    generic_found = [r for r in parsed["resources"] if r["is_generic"]]
    assert len(generic_found) >= 1
    assert any("generic" in r["name"].lower() for r in generic_found)


def test_upload_schedule_updates_portfolio_snapshot(client):
    # Create an updated project XML simulating PM working in MS Project
    # Download baseline template
    t_resp = client.get("/api/projects/1/template/xml")
    assert t_resp.status_code == 200

    # Modify percent complete and costs in XML
    root = ET.fromstring(t_resp.content.decode("utf-8"))
    ns = {"ms": "http://schemas.microsoft.com/project"}

    task_0 = None
    for task in root.findall(".//ms:Task", ns):
        uid = task.find("ms:UID", ns)
        if uid is not None and uid.text == "0":
            task_0 = task
            break
    assert task_0 is not None

    ns_url = "http://schemas.microsoft.com/project"
    pct_el = task_0.find("ms:PercentComplete", ns)
    if pct_el is None:
        pct_el = ET.SubElement(task_0, f"{{{ns_url}}}PercentComplete")
    pct_el.text = "45"

    pct_work_el = task_0.find("ms:PercentWorkComplete", ns)
    if pct_work_el is None:
        pct_work_el = ET.SubElement(task_0, f"{{{ns_url}}}PercentWorkComplete")
    pct_work_el.text = "50"

    cost_el = task_0.find("ms:Cost", ns)
    if cost_el is None:
        cost_el = ET.SubElement(task_0, f"{{{ns_url}}}Cost")
    cost_el.text = "12500.00"

    actual_cost_el = task_0.find("ms:ActualCost", ns)
    if actual_cost_el is None:
        actual_cost_el = ET.SubElement(task_0, f"{{{ns_url}}}ActualCost")
    actual_cost_el.text = "6000.00"

    modified_xml = ET.tostring(root, encoding="utf-8")

    # Upload to /api/projects/1/upload-schedule
    files = {"file": ("schedule_update.xml", modified_xml, "application/xml")}
    up_resp = client.post("/api/projects/1/upload-schedule", files=files)
    assert up_resp.status_code == 200
    up_data = up_resp.json()

    assert up_data["metrics"]["percent_complete"] == 45.0
    assert up_data["metrics"]["percent_work_complete"] == 50.0
    assert up_data["metrics"]["cost"] == 12500.0
    assert up_data["metrics"]["actual_cost"] == 6000.0

    # Verify portfolio view reflects the new snapshot
    port_resp = client.get("/api/portfolio")
    assert port_resp.status_code == 200
    portfolio = port_resp.json()

    # Find project 1 in portfolio
    p1 = None
    for group in portfolio["groups"]:
        for p in group["projects"]:
            if p["id"] == 1:
                p1 = p
                break
    assert p1 is not None
    assert p1["percent_complete"] == 45.0
    assert p1["percent_work_complete"] == 50.0
    assert p1["cost"] == 12500.0
    assert p1["actual_cost"] == 6000.0


def test_refresh_template_with_resource_swap(client):
    # Perform refresh with generic resource replacement
    # Swap "Mechanic (generic)" with named resource 1 (Tomas Petraitis)
    refresh_payload = {
        "resource_swaps": [
            {
                "generic_resource_name": "Mechanic (generic)",
                "named_resource_id": 1
            }
        ]
    }

    ref_resp = client.post("/api/projects/1/refresh", json=refresh_payload)
    assert ref_resp.status_code == 200
    assert "attachment;" in ref_resp.headers.get("content-disposition", "")

    # Parse refreshed XML
    ref_root = ET.fromstring(ref_resp.content.decode("utf-8"))
    ns = {"ms": "http://schemas.microsoft.com/project"}

    # Ensure active calendars and resources are present
    cal_nodes = ref_root.findall(".//ms:Calendar", ns)
    assert len(cal_nodes) >= 1

    res_names = [r.find("ms:Name", ns).text for r in ref_root.findall(".//ms:Resource", ns) if r.find("ms:Name", ns) is not None]
    assert "Tomas Petraitis" in res_names


def test_upload_schedule_rejects_mismatched_project(client):
    # Download template for Project 1 (ERP: 26-0537)
    t_resp = client.get("/api/projects/1/template/xml")
    assert t_resp.status_code == 200

    # Try uploading Project 1 schedule to Project 2 (ERP: 26-0608)
    files = {"file": ("schedule_update.xml", t_resp.content, "application/xml")}
    bad_resp = client.post("/api/projects/2/upload-schedule", files=files)
    assert bad_resp.status_code == 400
    assert "Project mismatch" in bad_resp.json()["detail"] or "verification error" in bad_resp.json()["detail"]


def test_portfolio_contains_last_updated_metadata(client):
    port_resp = client.get("/api/portfolio")
    assert port_resp.status_code == 200
    portfolio = port_resp.json()

    p1 = None
    for group in portfolio["groups"]:
        for p in group["projects"]:
            if p["id"] == 1:
                p1 = p
                break
    assert p1 is not None
    assert "last_updated_by" in p1
    assert "last_updated_at" in p1
    assert p1["last_updated_by"] is not None


def test_upload_schedule_baseline_and_budget_cost_ms_project_logic(client):
    # 1. Download template for Project 1
    t_resp = client.get("/api/projects/1/template/xml")
    assert t_resp.status_code == 200

    root = ET.fromstring(t_resp.content.decode("utf-8"))
    ns = {"ms": "http://schemas.microsoft.com/project"}
    ns_url = "http://schemas.microsoft.com/project"

    # Find or modify budget assignment on Task 0
    # In the template, assignment for budget resource exists on TaskUID 0
    asgns = root.findall(".//ms:Assignment", ns)
    budget_asgn = None
    for a in asgns:
        t_uid = a.find("ms:TaskUID", ns)
        if t_uid is not None and t_uid.text == "0":
            budget_asgn = a
            break

    if budget_asgn is None:
        budget_asgn = ET.SubElement(root.find(".//ms:Assignments", ns) or root, f"{{{ns_url}}}Assignment")
        t_uid = ET.SubElement(budget_asgn, f"{{{ns_url}}}TaskUID")
        t_uid.text = "0"
        r_uid = ET.SubElement(budget_asgn, f"{{{ns_url}}}ResourceUID")
        r_uid.text = "999999"

    # Set BudgetCost and BaselineBudgetCost on budget assignment
    b_cost_el = budget_asgn.find("ms:BudgetCost", ns)
    if b_cost_el is None:
        b_cost_el = ET.SubElement(budget_asgn, f"{{{ns_url}}}BudgetCost")
    b_cost_el.text = "60000.00"

    base_b_cost_el = budget_asgn.find("ms:BaselineBudgetCost", ns)
    if base_b_cost_el is None:
        base_b_cost_el = ET.SubElement(budget_asgn, f"{{{ns_url}}}BaselineBudgetCost")
    base_b_cost_el.text = "58000.00"

    # Ensure Task 0 does NOT have direct BaselineCost, testing leaf task roll-up
    tasks_node = root.find(".//ms:Tasks", ns) or root
    for t in root.findall(".//ms:Task", ns):
        uid = t.find("ms:UID", ns)
        if uid is not None and uid.text == "0":
            bc = t.find("ms:BaselineCost", ns)
            if bc is not None:
                t.remove(bc)
            for b in t.findall("ms:Baseline", ns):
                t.remove(b)

    # Add child leaf task under Tasks with BaselineCost to verify leaf rollup
    leaf_t = ET.SubElement(tasks_node, f"{{{ns_url}}}Task")
    leaf_uid = ET.SubElement(leaf_t, f"{{{ns_url}}}UID")
    leaf_uid.text = "1"
    leaf_summary = ET.SubElement(leaf_t, f"{{{ns_url}}}Summary")
    leaf_summary.text = "0"
    leaf_bc = ET.SubElement(leaf_t, f"{{{ns_url}}}BaselineCost")
    leaf_bc.text = "12500.00"

    modified_xml = ET.tostring(root, encoding="utf-8")

    # 2. Upload to /api/projects/1/upload-schedule
    files = {"file": ("budget_baseline_update.xml", modified_xml, "application/xml")}
    up_resp = client.post("/api/projects/1/upload-schedule", files=files)
    assert up_resp.status_code == 200
    metrics = up_resp.json()["metrics"]

    assert metrics["budget_cost"] == 60000.0
    assert metrics["baseline_budget"] == 58000.0
    assert metrics["baseline_cost"] > 0.0

    # 3. Check that Project master data (ProjectDB.budget_cost) was updated
    proj_resp = client.get("/api/projects/1")
    assert proj_resp.status_code == 200
    proj_data = proj_resp.json()
    assert proj_data["budget_cost"] == 60000.0

    # 4. Check that Portfolio view reflects budget and baseline metrics
    port_resp = client.get("/api/portfolio")
    assert port_resp.status_code == 200
    p1 = None
    for group in port_resp.json()["groups"]:
        for p in group["projects"]:
            if p["id"] == 1:
                p1 = p
                break
    assert p1 is not None
    assert p1["budget_cost"] == 60000.0
    assert p1["baseline_budget"] == 58000.0
    assert p1["baseline_cost"] == metrics["baseline_cost"]

