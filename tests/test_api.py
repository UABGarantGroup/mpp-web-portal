"""
Unit tests for FastAPI REST endpoints with database persistence.
"""

from datetime import date
import pytest

from backend.app.models.enums import RateTableEnum, ResourceKindEnum, ResourceTypeEnum
from backend.app.models.schemas import CostRateItem, ProjectTemplateRequest, ResourceModel


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "mpp-template-engine"


def test_calendars_endpoints(client):
    # List calendars
    resp = client.get("/api/calendars")
    assert resp.status_code == 200
    calendars = resp.json()
    assert len(calendars) >= 2

    # Supported countries
    resp_countries = client.get("/api/calendars/countries")
    assert resp_countries.status_code == 200
    countries = resp_countries.json()
    assert "LT" in countries
    assert "NO" in countries

    # Import holidays into calendar 1 (Admin role)
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}
    resp_import = client.post("/api/calendars/1/import-holidays?years=2026", headers=headers)
    assert resp_import.status_code == 200
    updated_cal = resp_import.json()
    assert len(updated_cal["exceptions"]) >= 4


def test_resources_crud_and_soft_delete(client):
    # List resources
    resp = client.get("/api/resources")
    assert resp.status_code == 200
    resources = resp.json()
    assert len(resources) >= 2

    # Filter by kind
    resp_generic = client.get("/api/resources?kind=Generic")
    assert resp_generic.status_code == 200
    generic_list = resp_generic.json()
    assert all(r["resource_kind"] == "Generic" for r in generic_list)

    # Soft delete resource 3 (Admin / RM role)
    headers = {"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"}
    resp_del = client.delete("/api/resources/3", headers=headers)
    assert resp_del.status_code == 200
    deleted_res = resp_del.json()
    assert deleted_res["is_active"] is False

    # Should not appear in standard list without include_inactive=True
    resp_active = client.get("/api/resources")
    assert all(r["id"] != 3 for r in resp_active.json())

    # Should appear when include_inactive=True
    resp_all = client.get("/api/resources?include_inactive=true")
    assert any(r["id"] == 3 for r in resp_all.json())


def test_update_rates_endpoint(client):
    new_rates = [
        {"rate_table": "A", "standard_rate": 52.00, "overtime_rate": 78.00, "cost_per_use": 0.0},
        {"rate_table": "B", "standard_rate": 68.00, "overtime_rate": 102.00, "cost_per_use": 0.0},
    ]
    headers = {"X-User-Role": "FinanceManager", "X-User-Email": "finance@enterprise.com"}
    resp = client.put("/api/resources/1/rates", json=new_rates, headers=headers)
    assert resp.status_code == 200
    rates = resp.json()
    assert len(rates) == 2
    assert rates[0]["standard_rate"] == 52.00


def test_export_xml_endpoint(client):
    payload = {
        "project_erp_number": "26-0537",
        "project_title": "26-0537 LA MANCHA KNUTSEN - assistance to Burckhardt",
        "company_name": "Enterprise Global",
        "start_date": "2026-08-25",
        "calendar_id": 1,
        "selected_resource_ids": [1, 2],
        "budget_cost": 332459.00,
        "custom_fields": [
            {
                "field_name": "Cost Center",
                "entity": "Resource",
                "field_type": "Text",
                "slot_number": 1,
                "alias": "Cost Center"
            }
        ],
        "project_custom_values": {}
    }
    resp = client.post("/api/templates/export/xml", json=payload)
    assert resp.status_code == 200
    assert "application/xml" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    xml_content = resp.text
    assert "<Project" in xml_content
    assert "BudgetCost>332459.00</BudgetCost>" in xml_content
