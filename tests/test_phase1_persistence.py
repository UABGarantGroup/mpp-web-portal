"""
Comprehensive tests for Phase 1: Database persistence, RBAC, soft-delete, and CSV/Excel import.
Uses shared database fixtures from conftest.py.
"""

from datetime import date
import io
import pytest

from backend.app.db.models import AuditLogDB, RatePeriodDB, ResourceDB


def test_db_seeding(db_session):
    resources = db_session.query(ResourceDB).all()
    assert len(resources) >= 3

    # Check Tomas Petraitis has Rate Tables configured
    tomas = db_session.query(ResourceDB).filter(ResourceDB.name == "Tomas Petraitis").first()
    assert tomas is not None
    assert len(tomas.rates) >= 2


def test_resource_soft_delete(client, db_session):
    # 1. Soft delete Tomas (ID 1)
    headers = {"X-User-Role": "ResourceManager", "X-User-Email": "rm@enterprise.com"}
    resp = client.delete("/api/resources/1", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # 2. Query active resources: ID 1 should not appear
    resp_active = client.get("/api/resources")
    assert all(r["id"] != 1 for r in resp_active.json())

    # 3. Query all resources including inactive: ID 1 must appear
    resp_all = client.get("/api/resources?include_inactive=true")
    assert any(r["id"] == 1 for r in resp_all.json())

    # 4. Reactivate for subsequent tests
    tomas = db_session.query(ResourceDB).filter(ResourceDB.id == 1).first()
    tomas.is_active = True
    db_session.commit()


def test_finance_manager_rate_rbac(client, db_session):
    new_rates = [
        {"rate_table": "A", "standard_rate": 55.0, "overtime_rate": 82.5, "cost_per_use": 0.0},
        {"rate_table": "B", "standard_rate": 70.0, "overtime_rate": 105.0, "cost_per_use": 0.0},
    ]

    # PM role should be FORBIDDEN (403) from updating rates
    headers_pm = {"X-User-Role": "PM", "X-User-Email": "pm@enterprise.com"}
    resp_pm = client.put("/api/resources/2/rates", json=new_rates, headers=headers_pm)
    assert resp_pm.status_code == 403

    # FinanceManager role should SUCCEED (200)
    headers_finance = {"X-User-Role": "FinanceManager", "X-User-Email": "finance@enterprise.com"}
    resp_fin = client.put("/api/resources/2/rates", json=new_rates, headers=headers_finance)
    assert resp_fin.status_code == 200
    rates_data = resp_fin.json()
    assert len(rates_data) == 2
    assert rates_data[0]["standard_rate"] == 55.0

    # Verify audit log was written
    audit = db_session.query(AuditLogDB).filter(AuditLogDB.entity_type == "RATE", AuditLogDB.entity_id == "2").first()
    assert audit is not None
    assert "finance@enterprise.com" in audit.changed_by


def test_generic_resource_creation_rbac(client):
    generic_payload = {
        "id": 99,
        "guid": "99999999-0000-0000-0000-000000000099",
        "name": "Electrician (generic)",
        "resource_kind": "Generic",
        "is_generic": True,
        "department": "Electrical",
    }

    # Resource Manager should be FORBIDDEN from creating generic resources (Admin-only supervisor rule)
    headers_rm = {"X-User-Role": "ResourceManager", "X-User-Email": "rm@enterprise.com"}
    resp_rm = client.post("/api/resources", json=generic_payload, headers=headers_rm)
    assert resp_rm.status_code == 403

    # Admin should SUCCEED
    headers_admin = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}
    resp_admin = client.post("/api/resources", json=generic_payload, headers=headers_admin)
    assert resp_admin.status_code == 201
    assert resp_admin.json()["name"] == "Electrician (generic)"


def test_csv_resource_import_validation(client):
    csv_content = """name,email,department,resource_type,resource_kind
Jonas Kazlauskas,jonas@enterprise.com,Operations,Work,Named
,invalid@enterprise.com,Engineering,Work,Named
Piping Specialist,,Operations,Work,Generic
"""
    files = {"file": ("resources.csv", csv_content.encode("utf-8"), "text/csv")}
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}

    # Dry run should preview and detect 1 error (missing name on row 3)
    resp = client.post("/api/import/resources?dry_run=true", files=files, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 3
    assert data["valid_count"] == 2
    assert data["error_count"] == 1
    assert data["errors"][0]["row"] == 3
    assert "Resource name is required" in data["errors"][0]["error"]


def test_csv_rate_import_validation(client):
    # Uses Tomas Petraitis (email: tomas.petraitis@enterprise.com)
    csv_content = """email,rate_table,standard_rate,overtime_rate,effective_date
tomas.petraitis@enterprise.com,A,48.00,72.00,2026-06-01
tomas.petraitis@enterprise.com,Z,50.00,75.00,2026-06-01
tomas.petraitis@enterprise.com,B,-10.00,0.00,2026-06-01
"""
    files = {"file": ("rates.csv", csv_content.encode("utf-8"), "text/csv")}
    headers = {"X-User-Role": "FinanceManager", "X-User-Email": "finance@enterprise.com"}

    resp = client.post("/api/import/rates?dry_run=true", files=files, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 3
    assert data["valid_count"] == 1
    assert data["error_count"] == 2
    # Invalid rate table 'Z'
    assert any("Invalid rate table 'Z'" in err["error"] for err in data["errors"])
    # Negative standard rate
    assert any("non-negative number" in err["error"] for err in data["errors"])


def test_export_template_from_db(client):
    payload = {
        "project_erp_number": "26-0999",
        "project_title": "26-0999 DATABASE PERSISTENCE TEST PROJECT",
        "company_name": "Enterprise Global",
        "start_date": "2026-09-01",
        "calendar_id": 1,
        "selected_resource_ids": [1, 2],
        "budget_cost": 250000.00,
        "custom_fields": [],
        "project_custom_values": {},
    }
    resp = client.post("/api/templates/export/xml", json=payload)
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    xml_text = resp.text
    assert "26-0999 DATABASE PERSISTENCE TEST PROJECT" in xml_text
    assert "<BudgetCost>250000.00</BudgetCost>" in xml_text
