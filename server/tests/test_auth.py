import base64
import json

import pytest
from fastapi.testclient import TestClient

from app import auth, config
from app.main import app

TENANT = "11111111-1111-1111-1111-111111111111"
OBJECT = "22222222-2222-2222-2222-222222222222"


def headers(roles=("Agency.deq",), tenant=TENANT):
    claims = [{"typ": "tid", "val": tenant}, {"typ": "oid", "val": OBJECT}]
    claims.extend({"typ": "roles", "val": role} for role in roles)
    principal = {"auth_typ": "aad", "claims": claims}
    return {"x-ms-client-principal": base64.b64encode(json.dumps(principal).encode()).decode()}


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "development")
    monkeypatch.setattr(config, "APP_ENV", "development")
    monkeypatch.delenv("CONTAINER_APP_NAME", raising=False)
    with TestClient(app) as client:
        monkeypatch.setattr(config, "AUTH_MODE", "entra")
        monkeypatch.setattr(config, "ENTRA_TENANT_ID", TENANT)
        monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://grants.example.test")
        yield client


@pytest.mark.parametrize("path", ["/api/meta", "/api/metrics", "/docs", "/openapi.json", "/", "/assets/test.js"])
def test_anonymous_denied_everywhere(secured, path):
    assert secured.get(path).status_code == 401
    assert secured.get("/healthz").status_code == 200


@pytest.mark.parametrize("principal", ["bad!", "e30=", "W10="])
def test_malformed_principal_rejected(secured, principal):
    assert secured.get("/api/meta", headers={"x-ms-client-principal": principal}).status_code == 401


def test_wrong_tenant_and_unassigned_roles(secured):
    assert secured.get("/api/meta", headers=headers(tenant=OBJECT)).status_code == 403
    assert secured.get("/api/meta", headers=headers(roles=())).status_code == 403
    assert secured.get("/api/meta", headers=headers(roles=("Agency.unknown",))).status_code == 403


def test_agency_picker_and_search_scoped(secured):
    response = secured.get("/api/meta", headers=headers())
    assert response.status_code == 200
    assert [a["id"] for a in response.json()["agencies"]] == ["deq"]
    assert secured.post("/api/search", json={"agency_id": "deq"}, headers=headers()).status_code == 200
    assert secured.get("/api/agencies/deq/projects", headers=headers()).status_code == 200


@pytest.mark.parametrize("path,body", [
    ("/api/search", {"agency_id": "dhhs"}),
    ("/api/export.csv", {"agency_id": "dhhs"}),
    ("/api/decisions", {"agency_id": "dhhs", "opportunity_id": "x", "action": "save"}),
    ("/api/subscriptions", {"agency_id": "dhhs", "email": "x@nc.gov"}),
    ("/api/subscriptions/preview", {"agency_id": "dhhs", "email": "x@nc.gov"}),
    ("/api/subscriptions/test", {"agency_id": "dhhs", "email": "x@nc.gov"}),
    ("/api/agencies/dhhs/projects", {"title": "Test project", "description": "Test description"}),
    ("/api/agencies/dhhs/documents", {"title": "Test document", "content": "x" * 60}),
])
def test_cross_agency_posts_rejected(secured, path, body):
    assert secured.post(path, json=body, headers=headers()).status_code == 403


@pytest.mark.parametrize("resource", ["projects", "documents"])
def test_cross_agency_get_delete_and_body_override_rejected(secured, resource):
    path = f"/api/agencies/dhhs/{resource}"
    assert secured.get(path, headers=headers()).status_code == 403
    assert secured.delete(path + "/1", headers=headers()).status_code == 403
    assert secured.post(path, json={"agency_id": "deq"}, headers=headers()).status_code == 403


def test_admin_only_metrics_and_ingest(secured, monkeypatch):
    from app import main
    assert secured.get("/api/metrics", headers=headers()).status_code == 403
    assert secured.post("/api/admin/ingest", headers=headers()).status_code == 403
    admin = headers(roles=("Matchmaker.Admin",))
    assert secured.get("/api/metrics", headers=admin).status_code == 200
    assert len(secured.get("/api/meta", headers=admin).json()["agencies"]) > 1
    monkeypatch.setattr(main.pipeline, "run", lambda **kwargs: None)
    assert secured.post("/api/admin/ingest", headers=admin).status_code == 200


def test_cross_origin_writes_and_form_json_rejected(secured):
    h = {**headers(), "origin": "https://attacker.test"}
    assert secured.post("/api/search", json={"agency_id": "deq"}, headers=h).status_code == 403
    assert secured.post("/api/search", content='{"agency_id":"deq"}', headers={**headers(), "content-type": "text/plain"}).status_code == 415
    h["origin"] = "https://grants.example.test"
    assert secured.post("/api/search", json={"agency_id": "deq"}, headers=h).status_code == 200


def test_authorized_project_write_and_delete(secured):
    body = {"title": "Water quality", "description": "Improve statewide water quality monitoring."}
    response = secured.post("/api/agencies/deq/projects", json=body, headers=headers())
    assert response.status_code == 200
    project_id = response.json()["id"]
    path = f"/api/agencies/deq/projects/{project_id}"
    assert secured.delete(path, headers=headers(roles=("Agency.dhhs",))).status_code == 403
    assert any(p["id"] == project_id for p in secured.get("/api/agencies/deq/projects", headers=headers()).json())
    assert secured.delete(path, headers=headers()).status_code == 200


def test_staff_confirmation_stays_protected(secured, monkeypatch):
    from app import emailer
    monkeypatch.setattr(emailer, "find_subscription", lambda token: {"agency_id": "dhhs"})
    for action in ("confirm",):
        path = f"/api/subscriptions/{action}?token=test"
        assert secured.get(path, headers=headers()).status_code == 403
        assert secured.post(path, headers=headers()).status_code == 403


def test_platform_mapped_claim_names(secured):
    claims = [
        {"typ": "http://schemas.microsoft.com/identity/claims/tenantid", "val": TENANT},
        {"typ": "http://schemas.microsoft.com/identity/claims/objectidentifier", "val": OBJECT},
        {"typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role", "val": "Agency.deq"},
    ]
    raw = base64.b64encode(json.dumps({"auth_typ": "aad", "claims": claims}).encode()).decode()
    assert secured.get("/api/meta", headers={"x-ms-client-principal": raw}).status_code == 200


def test_test_email_only_to_signed_in_worker(secured, monkeypatch):
    from app import emailer
    monkeypatch.setattr(emailer, "send_test_digest", lambda *args: {"delivery": {"delivered": True}})
    h = {**headers(), "x-ms-client-principal-name": "worker@nc.gov"}
    body = {"email": "someone-else@nc.gov", "agency_id": "deq", "top_n": 5}
    assert secured.post("/api/subscriptions/test", json=body, headers=h).status_code == 403
    assert secured.post("/api/subscriptions/test", json={**body, "email": "worker@nc.gov"}, headers=h).status_code == 200


def test_production_fails_closed(monkeypatch):
    monkeypatch.setattr(config, "AUTH_MODE", "development")
    monkeypatch.setattr(config, "APP_ENV", "production")
    with pytest.raises(RuntimeError, match="Production requires"):
        auth.validate_config()
    monkeypatch.setattr(config, "AUTH_MODE", "entra")
    monkeypatch.delenv("CONTAINER_APP_NAME", raising=False)
    with pytest.raises(RuntimeError, match="requires Azure"):
        auth.validate_config()
    monkeypatch.setenv("CONTAINER_APP_NAME", "test-app")
    monkeypatch.setattr(config, "ENTRA_TENANT_ID", "")
    with pytest.raises(RuntimeError, match="tenant UUID"):
        auth.validate_config()
    monkeypatch.setattr(config, "ENTRA_TENANT_ID", TENANT)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "http://localhost")
    with pytest.raises(RuntimeError, match="HTTPS"):
        auth.validate_config()
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", "https://grants.example.test")
    auth.validate_config()
