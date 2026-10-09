"""
Unit & Integration Tests for Phase 5:
- Selective Entra ID (Azure AD) user and security group lookups.
- Granting portal access by user email or security group.
- Adding resources to Master Resource Pool by user email or security group.
- Prevention of indiscriminate directory dumping.
"""

import pytest
from backend.app.db.models import PortalUserDB, ResourceDB, RatePeriodDB


def test_search_entra_users_and_groups(client):
    """Test searching Entra ID users and security groups."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    # Search users by name/keyword
    resp = client.get("/api/entra/users?q=Tomas", headers=headers)
    assert resp.status_code == 200
    users = resp.json()
    assert len(users) >= 1
    assert any("Tomas" in u["display_name"] for u in users)

    # Search groups
    resp = client.get("/api/entra/groups?q=Project", headers=headers)
    assert resp.status_code == 200
    groups = resp.json()
    assert len(groups) >= 1
    assert any("Project" in g["display_name"] for g in groups)

    # Get members of a security group
    group_id = groups[0]["id"]
    resp = client.get(f"/api/entra/groups/{group_id}/members", headers=headers)
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) >= 1
    assert "email" in members[0]


def test_add_portal_user_by_email(client, db_session):
    """Test adding a single portal user by email with specific role."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    payload = {
        "email": "tomas.jonaitis@garantgroup.eu",
        "role": "PM",
        "add_as_resource": False,
    }
    resp = client.post("/api/users/add-by-email", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "tomas.jonaitis@garantgroup.eu"
    assert data["role"] == "PM"
    assert data["is_active"] is True
    assert data["display_name"] == "Tomas Jonaitis"

    # Attempting duplicate should return 400
    resp_dup = client.post("/api/users/add-by-email", json=payload, headers=headers)
    assert resp_dup.status_code == 400


def test_add_portal_user_and_resource_simultaneously(client, db_session):
    """Test adding an Entra ID user as BOTH a portal user and a project resource."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    payload = {
        "email": "andrius.kazlauskas@garantgroup.eu",
        "role": "PM",
        "add_as_resource": True,
        "department": "Engineering",
        "base_calendar_id": 1,
        "standard_rate": 65.0,
    }
    resp = client.post("/api/users/add-by-email", json=payload, headers=headers)
    assert resp.status_code == 201

    # Verify user created in PortalUserDB
    p_user = db_session.query(PortalUserDB).filter(PortalUserDB.email == "andrius.kazlauskas@garantgroup.eu").first()
    assert p_user is not None
    assert p_user.role == "PM"

    # Verify resource created in ResourceDB
    res = db_session.query(ResourceDB).filter(ResourceDB.email == "andrius.kazlauskas@garantgroup.eu").first()
    assert res is not None
    assert res.name == "Andrius Kazlauskas"
    assert res.department == "Engineering"

    # Verify rate table A was populated
    rate = db_session.query(RatePeriodDB).filter(RatePeriodDB.resource_id == res.id).first()
    assert rate is not None
    assert rate.standard_rate == 65.0


def test_add_resource_from_entra_by_email(client, db_session):
    """Test selectively adding an individual resource from Entra ID."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    payload = {
        "email": "arturas.stankus@garantgroup.eu",
        "department": "Yard Operations",
        "base_calendar_id": 1,
        "standard_rate": 42.50,
        "overtime_rate": 63.75,
    }
    resp = client.post("/api/resources/add-by-email", json=payload, headers=headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Artūras Stankus"
    assert data["email"] == "arturas.stankus@garantgroup.eu"
    assert len(data["rates"]) >= 1
    assert data["rates"][0]["standard_rate"] == 42.50
    assert data["rates"][0]["overtime_rate"] == 63.75


def test_import_group_users_and_resources(client, db_session):
    """Test importing selected members of an Entra ID security group."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    payload = {
        "group_id": "sg-field-003",
        "group_name": "Yard & Workshop Technicians",
        "target": "BOTH",
        "user_role": "Viewer",
        "default_calendar_id": 1,
        "default_rate": 38.0,
    }
    resp = client.post("/api/users/import-group", json=payload, headers=headers)
    assert resp.status_code == 200
    res = resp.json()
    assert res["target"] == "BOTH"
    assert res["total_members"] == 3
    assert res["users_added"] >= 1
    assert res["resources_added"] >= 1


def test_manage_portal_user_roles_and_deactivation(client, db_session):
    """Test updating user role and deactivating portal access."""
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    # Create user
    create_resp = client.post(
        "/api/users/add-by-email",
        json={"email": "elena.petrauskiene@garantgroup.eu", "role": "PM"},
        headers=headers,
    )
    user_id = create_resp.json()["id"]

    # Update role to FinanceManager
    update_resp = client.put(
        f"/api/users/{user_id}",
        json={"role": "FinanceManager"},
        headers=headers,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["role"] == "FinanceManager"

    # Deactivate user
    del_resp = client.delete(f"/api/users/{user_id}", headers=headers)
    assert del_resp.status_code == 200

    # User should now be inactive
    p_user = db_session.query(PortalUserDB).filter(PortalUserDB.id == user_id).first()
    assert p_user.is_active is False
