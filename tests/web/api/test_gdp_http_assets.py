from __future__ import annotations

import tempfile
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.api.gdp_http_assets import router as gdp_http_assets_router
from xagent.web.auth_dependencies import get_current_user
from xagent.web.models.database import Base, get_db
from xagent.web.models.user import User


def _build_client() -> tuple[
    TestClient,
    sessionmaker,
    object,
    User,
    User,
    Callable[[User], None],
]:
    temp_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_file.close()

    engine = create_engine(
        f"sqlite:///{temp_file.name}", connect_args={"check_same_thread": False}
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    user_a = User(username="creator", password_hash="hashed", is_admin=False)
    user_b = User(username="viewer", password_hash="hashed", is_admin=False)
    db.add_all([user_a, user_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    db.close()

    app = FastAPI()
    app.include_router(gdp_http_assets_router)

    current_user = {"value": user_a}

    def override_get_db():
        db_session = SessionLocal()
        try:
            yield db_session
        finally:
            db_session.close()

    def set_current_user(user: User) -> None:
        current_user["value"] = user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user["value"]

    return TestClient(app), SessionLocal, engine, user_a, user_b, set_current_user


def _valid_payload(*, visibility: str = "private") -> dict:
    return {
        "resource": {
            "resource_key": "crm_create_signup",
            "system_short": "crm",
            "visibility": visibility,
            "summary": "营销报名创建接口",
            "tags_json": ["crm", "signup"],
        },
        "tool_contract": {
            "tool_name": "create_signup",
            "tool_description": "向营销系统创建报名记录，并返回 signup_id",
            "input_schema_json": {
                "type": "object",
                "properties": {
                    "customerId": {"type": "string"},
                },
                "required": ["customerId"],
            },
            "output_schema_json": {
                "type": "object",
                "properties": {
                    "signupId": {"type": "string"},
                },
            },
            "annotations_json": {
                "title": "创建报名记录",
                "readOnlyHint": False,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
        "execution_profile": {
            "method": "POST",
            "url_mode": "direct",
            "direct_url": "https://api.example.com/signup",
            "sys_label": None,
            "url_suffix": None,
            "args_position_json": {
                "customerId": {"in": "query", "name": "customer_id"},
            },
            "request_template_json": {},
            "response_template_json": {},
            "error_response_template": "接口失败：HTTP {{ status_code }}",
            "auth_json": {},
            "headers_json": {},
            "timeout_seconds": 30,
        },
    }


def test_create_and_list_gdp_http_assets():
    client, _, engine, _, _, _ = _build_client()
    try:
        create_response = client.post("/api/v1/gdp/http-assets", json=_valid_payload())

        assert create_response.status_code == 200
        detail = create_response.json()["data"]
        assert detail["resource"]["resource_key"] == "crm_create_signup"
        assert detail["resource"]["system_short"] == "crm"
        assert detail["resource"]["create_user_name"] == "creator"
        assert detail["resource"]["status"] == 1

        list_response = client.get("/api/v1/gdp/http-assets")

        assert list_response.status_code == 200
        items = list_response.json()["data"]
        assert len(items) == 1
        assert items[0]["resource_key"] == "crm_create_signup"
        assert items[0]["system_short"] == "crm"
        assert items[0]["status"] == 1
    finally:
        engine.dispose()


def test_shared_asset_is_visible_to_other_user():
    client, _, engine, _, user_b, set_current_user = _build_client()
    try:
        create_response = client.post(
            "/api/v1/gdp/http-assets",
            json=_valid_payload(visibility="shared"),
        )
        assert create_response.status_code == 200

        set_current_user(user_b)

        list_response = client.get("/api/v1/gdp/http-assets")
        assert list_response.status_code == 200
        items = list_response.json()["data"]
        assert len(items) == 1
        assert items[0]["visibility"] == "shared"

        asset_id = create_response.json()["data"]["resource"]["id"]
        detail_response = client.get(f"/api/v1/gdp/http-assets/{asset_id}")
        assert detail_response.status_code == 200
        assert (
            detail_response.json()["data"]["tool_contract"]["tool_name"]
            == "create_signup"
        )
    finally:
        engine.dispose()


def test_create_rejects_unknown_args_position_source_path():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["args_position_json"] = {
            "missingField": {"in": "query", "name": "missing_field"}
        }

        response = client.post("/api/v1/gdp/http-assets", json=payload)

        assert response.status_code == 400
        assert "source path" in response.json()["detail"]
    finally:
        engine.dispose()


def test_delete_is_soft_delete_and_hidden_from_list():
    client, _, engine, _, _, _ = _build_client()
    try:
        create_response = client.post("/api/v1/gdp/http-assets", json=_valid_payload())
        assert create_response.status_code == 200
        asset_id = create_response.json()["data"]["resource"]["id"]

        delete_response = client.delete(f"/api/v1/gdp/http-assets/{asset_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["data"]["status"] == 2

        list_response = client.get("/api/v1/gdp/http-assets")
        assert list_response.status_code == 200
        assert list_response.json()["data"] == []

        detail_response = client.get(f"/api/v1/gdp/http-assets/{asset_id}")
        assert detail_response.status_code == 404

        update_response = client.put(
            f"/api/v1/gdp/http-assets/{asset_id}",
            json=_valid_payload(),
        )
        assert update_response.status_code == 404
    finally:
        engine.dispose()
