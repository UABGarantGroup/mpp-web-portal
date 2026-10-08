"""
Tests for Phase 2 & Phase 3:
- Project creation and retrieval
- Finance Manager budget governance
- Portfolio stage definition and blocking
- Stage status transitions (Done, Not Done, N/A)
- Portfolio center summary aggregation grouped by owner
- MS Project XML template download for a specific project
"""

import xml.etree.ElementTree as ET
import pytest
from backend.app.models.schemas import StageStatusEnum


def test_get_stage_definitions(client):
    response = client.get("/api/stages")
    assert response.status_code == 200
    stages = response.json()
    assert len(stages) >= 8
    stage_codes = [s["code"] for s in stages]
    assert "tabelis" in stage_codes
    assert "saskaita" in stage_codes
    assert "darbu_aktas" in stage_codes
    assert "admin" in stage_codes


def test_block_unblock_stage(client):
    stages = client.get("/api/stages").json()
    stage_id = stages[0]["id"]

    # Block stage as Admin
    resp_block = client.put(
        f"/api/stages/{stage_id}/block?is_active=false",
        headers={"X-User-Role": "Admin", "X-User-Email": "admin@garant.eu"}
    )
    assert resp_block.status_code == 200
    assert resp_block.json()["is_active"] is False

    # PM should not be allowed to block stage
    resp_pm_block = client.put(
        f"/api/stages/{stage_id}/block?is_active=true",
        headers={"X-User-Role": "PM", "X-User-Email": "pm@garant.eu"}
    )
    assert resp_pm_block.status_code == 403

    # Unblock stage as Admin
    resp_unblock = client.put(
        f"/api/stages/{stage_id}/block?is_active=true",
        headers={"X-User-Role": "Admin", "X-User-Email": "admin@garant.eu"}
    )
    assert resp_unblock.status_code == 200
    assert resp_unblock.json()["is_active"] is True


def test_create_and_get_project(client):
    new_proj = {
        "erp_number": "26-9999",
        "name": "MV Baltic Test Vessel Overhaul",
        "owner": "Jonas Jonaitis",
        "start_date": "2026-06-01",
        "calendar_id": 1,
        "budget_cost": 45000.0,
        "team_resource_ids": [1, 2]
    }
    create_resp = client.post(
        "/api/projects",
        json=new_proj,
        headers={"X-User-Role": "PM", "X-User-Email": "jonas@garant.eu"}
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    proj_id = created_data["id"]
    assert created_data["erp_number"] == "26-9999"
    assert created_data["budget_cost"] == 45000.0
    assert len(created_data["stage_statuses"]) >= 8

    # Fetch project details
    get_resp = client.get(f"/api/projects/{proj_id}")
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["name"] == "MV Baltic Test Vessel Overhaul"
    assert len(detail["team_members"]) == 2


def test_finance_manager_budget_update(client):
    # Get a project
    projs = client.get("/api/projects").json()
    proj_id = projs[0]["id"]

    # PM cannot update budget
    pm_resp = client.put(
        f"/api/projects/{proj_id}/budget",
        json={"budget_cost": 99999.0},
        headers={"X-User-Role": "PM", "X-User-Email": "pm@garant.eu"}
    )
    assert pm_resp.status_code == 403

    # FinanceManager can update budget
    fm_resp = client.put(
        f"/api/projects/{proj_id}/budget",
        json={"budget_cost": 88000.0},
        headers={"X-User-Role": "FinanceManager", "X-User-Email": "cfo@garant.eu"}
    )
    assert fm_resp.status_code == 200
    assert fm_resp.json()["budget_cost"] == 88000.0


def test_stage_status_update_and_blocking(client):
    projs = client.get("/api/projects").json()
    proj = projs[0]
    proj_id = proj["id"]
    stages = client.get("/api/stages").json()
    stage_id = stages[0]["id"]

    # Unauthorized PM should receive 403
    resp_unauth = client.put(
        f"/api/projects/{proj_id}/stages/{stage_id}",
        json={"status": StageStatusEnum.DONE.value},
        headers={"X-User-Role": "PM", "X-User-Email": "unauthorized_pm@garant.eu"}
    )
    assert resp_unauth.status_code == 403

    # Authorized PM (domas) toggles to Done
    resp_done = client.put(
        f"/api/projects/{proj_id}/stages/{stage_id}",
        json={"status": StageStatusEnum.DONE.value},
        headers={"X-User-Role": "PM", "X-User-Email": "domas@garant.eu"}
    )
    assert resp_done.status_code == 200
    assert resp_done.json()["status"] == "Done"

    # Authorized PM toggles to NA
    resp_na = client.put(
        f"/api/projects/{proj_id}/stages/{stage_id}",
        json={"status": StageStatusEnum.NOT_APPLICABLE.value},
        headers={"X-User-Role": "PM", "X-User-Email": "domas@garant.eu"}
    )
    assert resp_na.status_code == 200
    assert resp_na.json()["status"] == "Not applicable"

    # Block stage as Admin
    client.put(
        f"/api/stages/{stage_id}/block?is_active=false",
        headers={"X-User-Role": "Admin", "X-User-Email": "admin@garant.eu"}
    )

    # Attempt to update blocked stage
    resp_blocked_update = client.put(
        f"/api/projects/{proj_id}/stages/{stage_id}",
        json={"status": StageStatusEnum.NOT_DONE.value},
        headers={"X-User-Role": "PM", "X-User-Email": "domas@garant.eu"}
    )
    assert resp_blocked_update.status_code == 400
    assert "blocked" in resp_blocked_update.json()["detail"].lower()

    # Unblock
    client.put(
        f"/api/stages/{stage_id}/block?is_active=true",
        headers={"X-User-Role": "Admin", "X-User-Email": "admin@garant.eu"}
    )


def test_portfolio_grouped_endpoint(client):
    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()
    assert "groups" in data
    assert "stage_columns" in data
    assert len(data["stage_columns"]) >= 8
    assert len(data["groups"]) >= 1

    # Check summary aggregation
    first_group = data["groups"][0]
    assert "owner" in first_group
    assert "summary" in first_group
    assert "total_budget_cost" in first_group["summary"]
    assert "total_cost" in first_group["summary"]
    assert "total_baseline_cost" in first_group["summary"]
    assert "projects" in first_group
    assert len(first_group["projects"]) >= 1


def test_export_project_template_xml(client):
    projs = client.get("/api/projects").json()
    proj = projs[0]
    proj_id = proj["id"]

    resp = client.post(f"/api/projects/{proj_id}/template/xml")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert f"{proj['erp_number']}" in resp.headers["content-disposition"]

    xml_text = resp.text
    root = ET.fromstring(xml_text)
    ns = {"ms": "http://schemas.microsoft.com/project"}

    # Check Title and Project Name
    title_elem = root.find("ms:Title", ns)
    assert title_elem is not None
    assert proj["erp_number"] in title_elem.text

    # Check Task 0 Budget Cost
    task_0 = None
    for task in root.findall(".//ms:Task", ns):
        uid = task.find("ms:UID", ns)
        if uid is not None and uid.text == "0":
            task_0 = task
            break
    assert task_0 is not None

    # Check Task 0 budget assignment with BudgetCost tag
    assignment_0 = None
    for asgn in root.findall(".//ms:Assignment", ns):
        t_uid = asgn.find("ms:TaskUID", ns)
        if t_uid is not None and t_uid.text == "0":
            assignment_0 = asgn
            break
    assert assignment_0 is not None
    b_cost = assignment_0.find("ms:BudgetCost", ns)
    assert b_cost is not None
    assert float(b_cost.text) == pytest.approx(proj["budget_cost"], 0.01)
