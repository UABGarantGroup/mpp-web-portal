"""
Unit and integration tests for:
1. Default Admin onboarding from Entra ID / INITIAL_ADMIN_EMAIL.
2. SSO authentication config and /api/auth/me profile endpoint.
3. Least privilege login (minimum role PM) and PM project isolation (PM only sees their own projects).
4. Default OPEN project filtering and project status toggle (OPEN / CLOSED).
"""

import pytest
from datetime import date
from backend.app.db.models import ProjectDB, PortalUserDB
from backend.app.core.config import settings


def test_auth_config_endpoint(client):
    """Test public SSO config endpoint for MSAL frontend."""
    resp = client.get("/api/auth/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "tenant_id" in data
    assert "client_id" in data
    assert "auth_enabled" in data


def test_auth_me_endpoint_dev_and_admin(client):
    """Test /api/auth/me returns authenticated profile and role."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True
    assert data["email"] == "admin@enterprise.com"
    assert data["primary_role"] == "Admin"
    assert data["is_admin"] is True


def test_initial_admin_bootstrap(client, db_session, monkeypatch):
    """Test that setting INITIAL_ADMIN_EMAIL auto-provisions or recognizes admin on login."""
    test_admin_email = "bootstrap.admin@garantgroup.eu"
    monkeypatch.setattr(settings, "INITIAL_ADMIN_EMAIL", test_admin_email)

    # Simulate Entra ID token with preferred_username matching INITIAL_ADMIN_EMAIL
    import jwt
    mock_token = jwt.encode({"preferred_username": test_admin_email, "name": "Bootstrap Admin"}, "secret", algorithm="HS256")
    headers = {"Authorization": f"Bearer {mock_token}"}

    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == test_admin_email
    assert data["primary_role"] == "Admin"
    assert data["is_admin"] is True

    # Verify user was saved in PortalUserDB as Admin
    p_user = db_session.query(PortalUserDB).filter(PortalUserDB.email.ilike(test_admin_email)).first()
    assert p_user is not None
    assert p_user.role == "Admin"
    assert p_user.source == "INITIAL_SETUP"


def test_pm_project_isolation(client, db_session):
    """Test least privilege: PM can ONLY see their own projects, while Admin sees all."""
    # Create two projects owned by different PMs
    p1 = ProjectDB(
        erp_number="26-TEST-PM1",
        name="Hull Repair 01",
        owner="pm1@garantgroup.eu",
        start_date=date(2026, 4, 1),
        calendar_id=1,
        budget_cost=50000.0,
        status="OPEN",
    )
    p2 = ProjectDB(
        erp_number="26-TEST-PM2",
        name="Electrical Overhaul 02",
        owner="pm2@garantgroup.eu",
        start_date=date(2026, 4, 15),
        calendar_id=1,
        budget_cost=30000.0,
        status="OPEN",
    )
    db_session.add_all([p1, p2])
    db_session.commit()

    # PM 1 logs in
    pm1_headers = {"X-User-Role": "PM", "X-User-Email": "pm1@garantgroup.eu"}
    resp = client.get("/api/projects", headers=pm1_headers)
    assert resp.status_code == 200
    pm1_projects = resp.json()
    assert any(p["erp_number"] == "26-TEST-PM1" for p in pm1_projects)
    assert not any(p["erp_number"] == "26-TEST-PM2" for p in pm1_projects)

    # In portfolio view, PM 1 only sees their group
    resp_port = client.get("/api/portfolio", headers=pm1_headers)
    assert resp_port.status_code == 200
    port_data = resp_port.json()
    owners = [g["owner"] for g in port_data["groups"]]
    assert "pm1@garantgroup.eu" in owners
    assert "pm2@garantgroup.eu" not in owners

    # Admin logs in -> sees BOTH projects
    admin_headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}
    resp_admin = client.get("/api/projects", headers=admin_headers)
    assert resp_admin.status_code == 200
    admin_projects = resp_admin.json()
    assert any(p["erp_number"] == "26-TEST-PM1" for p in admin_projects)
    assert any(p["erp_number"] == "26-TEST-PM2" for p in admin_projects)


def test_default_open_project_filter_and_toggle_status(client, db_session):
    """Test default project filtering shows only OPEN projects, and status can be updated."""
    admin_headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    # Create one open project and one closed project
    p_open = ProjectDB(
        erp_number="26-STATUS-OPEN",
        name="Active Drydock Works",
        owner="tomas.jonaitis@garantgroup.eu",
        start_date=date(2026, 5, 1),
        calendar_id=1,
        budget_cost=10000.0,
        status="OPEN",
    )
    p_closed = ProjectDB(
        erp_number="26-STATUS-CLOSED",
        name="Finished Inspection",
        owner="tomas.jonaitis@garantgroup.eu",
        start_date=date(2026, 1, 1),
        calendar_id=1,
        budget_cost=5000.0,
        status="CLOSED",
    )
    db_session.add_all([p_open, p_closed])
    db_session.commit()

    # 1. Default portfolio query (no status param) must return ONLY OPEN projects
    resp_default = client.get("/api/portfolio", headers=admin_headers)
    assert resp_default.status_code == 200
    groups_default = resp_default.json()["groups"]
    all_default_erps = [p["erp_number"] for g in groups_default for p in g["projects"]]
    assert "26-STATUS-OPEN" in all_default_erps
    assert "26-STATUS-CLOSED" not in all_default_erps

    # 2. Query with ?status=CLOSED returns ONLY CLOSED projects
    resp_closed = client.get("/api/portfolio?status=CLOSED", headers=admin_headers)
    assert resp_closed.status_code == 200
    groups_closed = resp_closed.json()["groups"]
    all_closed_erps = [p["erp_number"] for g in groups_closed for p in g["projects"]]
    assert "26-STATUS-CLOSED" in all_closed_erps
    assert "26-STATUS-OPEN" not in all_closed_erps

    # 3. Query with ?status=ALL returns both
    resp_all = client.get("/api/portfolio?status=ALL", headers=admin_headers)
    assert resp_all.status_code == 200
    groups_all = resp_all.json()["groups"]
    all_erps = [p["erp_number"] for g in groups_all for p in g["projects"]]
    assert "26-STATUS-OPEN" in all_erps
    assert "26-STATUS-CLOSED" in all_erps

    # 4. Toggle open project to CLOSED via PATCH /api/projects/{id}/status
    patch_resp = client.patch(
        f"/api/projects/{p_open.id}/status",
        json={"status": "CLOSED"},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "CLOSED"

    # Now p_open should no longer appear in default OPEN view
    resp_after = client.get("/api/portfolio", headers=admin_headers)
    all_after_erps = [p["erp_number"] for g in resp_after.json()["groups"] for p in g["projects"]]
    assert "26-STATUS-OPEN" not in all_after_erps
