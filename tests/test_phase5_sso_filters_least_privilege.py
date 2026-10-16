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
    assert "emergency_login_enabled" in data


def test_strict_auth_blocks_unauthenticated_requests(client, monkeypatch):
    """When AUTH_ENABLED=True, unauthenticated requests to any data endpoint must be rejected with 401."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)

    for endpoint in ["/api/auth/me", "/api/portfolio", "/api/projects", "/api/resources", "/api/calendars"]:
        resp = client.get(endpoint)
        assert resp.status_code == 401, f"Expected 401 for {endpoint}, got {resp.status_code}"

    # Even if dev headers X-User-Role are passed, AUTH_ENABLED=True must reject without a valid Bearer token
    resp_with_dev_header = client.get(
        "/api/portfolio",
        headers={"X-User-Role": "Admin", "X-User-Email": "admin@enterprise.com"},
    )
    assert resp_with_dev_header.status_code == 401


def test_emergency_admin_login_and_onboarding(client, db_session, monkeypatch):
    """Test Emergency (Onboarding) Admin login from .env credentials and onboarding a first Entra ID Admin."""
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_USERNAME", "emergency_admin")
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_PASSWORD", "Test_Emergency_Secret_2026!")

    # 1. Invalid password -> 401
    bad_resp = client.post(
        "/api/auth/emergency-login",
        json={"username": "emergency_admin", "password": "wrong_password"},
    )
    assert bad_resp.status_code == 401

    # 2. Valid emergency credentials -> 200 + signed JWT token
    ok_resp = client.post(
        "/api/auth/emergency-login",
        json={"username": "emergency_admin", "password": "Test_Emergency_Secret_2026!"},
    )
    assert ok_resp.status_code == 200
    token_data = ok_resp.json()
    assert "access_token" in token_data
    assert token_data["user"]["is_admin"] is True
    emergency_headers = {"Authorization": f"Bearer {token_data['access_token']}"}

    # 3. Verify Emergency Admin can access /api/auth/me and /api/portfolio when AUTH_ENABLED=True
    me_resp = client.get("/api/auth/me", headers=emergency_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["primary_role"] == "Admin"

    port_resp = client.get("/api/portfolio", headers=emergency_headers)
    assert port_resp.status_code == 200

    # 4a. Verify forged/untrusted JWT signature is rejected (401 Unauthorized)
    import jwt
    forged_token = jwt.encode(
        {"preferred_username": "new.pm@garantgroup.eu", "name": "New PM"},
        "forged_attacker_key",
        algorithm="HS256",
    )
    forged_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert forged_resp.status_code == 401

    # 4b. Verify valid signed SSO session token for un-onboarded Entra ID user is denied access (403 Forbidden)
    unregistered_token = jwt.encode(
        {"preferred_username": "new.pm@garantgroup.eu", "name": "New PM", "auth_type": "SSO_SESSION"},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    unreg_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {unregistered_token}"})
    assert unreg_resp.status_code == 403


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

    # Simulate verified SSO session token with preferred_username matching INITIAL_ADMIN_EMAIL
    import jwt
    mock_token = jwt.encode(
        {"preferred_username": test_admin_email, "name": "Bootstrap Admin", "auth_type": "SSO_SESSION"},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
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


def test_sso_exchange_enforces_id_token_and_aud_tid_claims(client, monkeypatch):
    """
    Verifies HIGH-1:
    - Rejects OAuth2 responses missing id_token (does not fall back to access_token).
    - Rejects id_token with mismatched aud (Client ID) or tid (Tenant ID).
    - Accepts valid id_token with matching aud and tid and forwards PKCE code_verifier.
    """
    import httpx
    import jwt
    from unittest.mock import MagicMock
    from backend.app.api.routes import _AUTH_FAILED_ATTEMPTS

    _AUTH_FAILED_ATTEMPTS.clear()
    monkeypatch.setattr(settings, "AZURE_AD_TENANT_ID", "tenant-1111")
    monkeypatch.setattr(settings, "AZURE_AD_CLIENT_ID", "client-2222")
    monkeypatch.setattr(settings, "AZURE_AD_CLIENT_SECRET", "secret-3333")

    captured_payloads = []
    orig_post = httpx.Client.post

    def make_mock_post(token_response_dict):
        def _mock_post(self, url, *args, **kwargs):
            if "login.microsoftonline.com" in str(url):
                captured_payloads.append(kwargs.get("data"))
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = token_response_dict
                return resp
            return orig_post(self, url, *args, **kwargs)
        return _mock_post

    # 1. Missing id_token (only access_token returned) -> must reject 401
    only_access_jwt = jwt.encode(
        {"preferred_username": "pm@garantgroup.eu", "aud": "https://graph.microsoft.com"},
        "dummy",
        algorithm="HS256",
    )
    monkeypatch.setattr(httpx.Client, "post", make_mock_post({"access_token": only_access_jwt}))
    r1 = client.post("/api/auth/sso/exchange", json={"code": "c1", "redirect_uri": "http://localhost:8000"})
    assert r1.status_code == 401

    # 2. Wrong audience (aud mismatch) -> must reject 401
    wrong_aud_jwt = jwt.encode(
        {"preferred_username": "pm@garantgroup.eu", "aud": "wrong-client-id", "tid": "tenant-1111"},
        "dummy",
        algorithm="HS256",
    )
    monkeypatch.setattr(httpx.Client, "post", make_mock_post({"id_token": wrong_aud_jwt}))
    r2 = client.post("/api/auth/sso/exchange", json={"code": "c2", "redirect_uri": "http://localhost:8000"})
    assert r2.status_code == 401
    assert "aud" in r2.json()["detail"]

    # 3. Wrong tenant (tid mismatch) -> must reject 401
    wrong_tid_jwt = jwt.encode(
        {"preferred_username": "pm@garantgroup.eu", "aud": "client-2222", "tid": "attacker-tenant-9999"},
        "dummy",
        algorithm="HS256",
    )
    monkeypatch.setattr(httpx.Client, "post", make_mock_post({"id_token": wrong_tid_jwt}))
    r3 = client.post("/api/auth/sso/exchange", json={"code": "c3", "redirect_uri": "http://localhost:8000"})
    assert r3.status_code == 401
    assert "tid" in r3.json()["detail"]

    # 4. Matching aud and tid + PKCE code_verifier -> 200 OK
    valid_id_jwt = jwt.encode(
        {"preferred_username": "domas.krupavicius@garantgroup.eu", "name": "Domas Krupavičius", "aud": "client-2222", "tid": "tenant-1111"},
        "dummy",
        algorithm="HS256",
    )
    monkeypatch.setattr(httpx.Client, "post", make_mock_post({"id_token": valid_id_jwt}))
    r4 = client.post(
        "/api/auth/sso/exchange",
        json={"code": "c4", "redirect_uri": "http://localhost:8000", "code_verifier": "pkce_verifier_secret_123"},
    )
    assert r4.status_code == 200
    assert "access_token" in r4.json()
    assert captured_payloads[-1].get("code_verifier") == "pkce_verifier_secret_123"
    _AUTH_FAILED_ATTEMPTS.clear()


def test_rate_limiter_resists_x_forwarded_for_spoofing(client, monkeypatch):
    """
    Verifies HIGH-2:
    Sending forged X-Forwarded-For headers with rotating random IPs cannot bypass
    brute-force rate limiting on /api/auth/emergency-login.
    """
    from backend.app.api.routes import _AUTH_FAILED_ATTEMPTS, _AUTH_MAX_FAILED_ATTEMPTS

    _AUTH_FAILED_ATTEMPTS.clear()
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_USERNAME", "emergency_admin")
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_PASSWORD", "Correct_Horse_Battery_Staple_2026!")

    for i in range(_AUTH_MAX_FAILED_ATTEMPTS):
        resp = client.post(
            "/api/auth/emergency-login",
            json={"username": "emergency_admin", "password": f"wrong_pass_{i}"},
            headers={"X-Forwarded-For": f"203.0.113.{i + 1}"},
        )
        assert resp.status_code == 401

    # 9th attempt with a brand-new forged X-Forwarded-For IP must be blocked with 429 Too Many Requests
    blocked_resp = client.post(
        "/api/auth/emergency-login",
        json={"username": "emergency_admin", "password": "another_wrong_pass"},
        headers={"X-Forwarded-For": "198.51.100.250"},
    )
    assert blocked_resp.status_code == 429
    _AUTH_FAILED_ATTEMPTS.clear()


def test_entra_config_blocks_runtime_env_overwrite_in_production(client, monkeypatch):
    """
    Verifies HIGH-4:
    POST /api/entra/config must reject runtime .env modification with 403 when ENVIRONMENT == 'production'.
    """
    import jwt

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)

    admin_token = jwt.encode(
        {"sub": "admin@enterprise.com", "email": "admin@enterprise.com", "roles": ["Admin"], "auth_type": "SSO_SESSION"},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    resp = client.post(
        "/api/entra/config",
        json={
            "tenant_id": "attacker-tenant-id",
            "client_id": "attacker-client-id",
            "client_secret": "attacker-secret",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403
    assert "disabled in production" in resp.json()["detail"]


def test_dockerfile_non_root_user_and_compose_security_opt():
    """
    Verifies HIGH-3:
    Dockerfile drops privileges to non-root USER mppuser and Docker Compose files enforce no-new-privileges:true.
    """
    import os

    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(root_dir, "Dockerfile"), "r", encoding="utf-8") as f:
        dockerfile_content = f.read()
    assert "USER mppuser" in dockerfile_content

    for compose_file in ["docker-compose.yml", "docker-compose.mssql.yml", "docker-compose.external-db.yml"]:
        with open(os.path.join(root_dir, compose_file), "r", encoding="utf-8") as f:
            compose_content = f.read()
        assert "no-new-privileges:true" in compose_content

