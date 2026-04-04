from __future__ import annotations

import tempfile
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.api.gdp_http_assets import router as gdp_http_assets_router
from xagent.web.api.system_registry import router as system_registry_router
from xagent.web.auth_dependencies import get_current_user
from xagent.web.models.database import Base, get_db
from xagent.web.models.system_approval import SystemRegistry, UserSystemRole
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
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    user_a = User(username="creator", password_hash="hashed", is_admin=False)
    user_b = User(username="viewer", password_hash="hashed", is_admin=False)
    db.add_all([user_a, user_b])
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    db.add(
        SystemRegistry(
            system_short="CRM",
            display_name="CRM",
            status="active",
            created_by=int(user_a.id),
        )
    )
    db.add(
        UserSystemRole(
            user_id=int(user_a.id),
            system_short="CRM",
            role="system_admin",
            granted_by=int(user_a.id),
        )
    )
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(system_registry_router)
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


def _approve_request(client: TestClient, request_id: int) -> None:
    response = client.post(
        f"/api/asset-change-requests/{request_id}/approve",
        json={"comment": "approved"},
    )
    assert response.status_code == 200


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
        assert detail["asset_type"] == "http_resource"
        assert detail["status"] == "pending_approval"
        assert detail["system_short"] == "CRM"

        _approve_request(client, int(detail["id"]))

        list_response = client.get("/api/v1/gdp/http-assets")

        assert list_response.status_code == 200
        items = list_response.json()["data"]
        assert len(items) == 1
        assert items[0]["resource_key"] == "crm_create_signup"
        assert items[0]["system_short"] == "CRM"
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
        request_id = int(create_response.json()["data"]["id"])
        _approve_request(client, request_id)

        set_current_user(user_b)

        list_response = client.get("/api/v1/gdp/http-assets")
        assert list_response.status_code == 200
        items = list_response.json()["data"]
        assert len(items) == 1
        assert items[0]["visibility"] == "shared"

        asset_id = items[0]["id"]
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
        create_request_id = int(create_response.json()["data"]["id"])
        _approve_request(client, create_request_id)

        asset_id = client.get("/api/v1/gdp/http-assets").json()["data"][0]["id"]

        delete_response = client.delete(f"/api/v1/gdp/http-assets/{asset_id}")
        assert delete_response.status_code == 200
        delete_request_id = int(delete_response.json()["data"]["id"])
        assert delete_response.json()["data"]["status"] == "pending_approval"
        _approve_request(client, delete_request_id)

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


def test_create_rejects_duplicate_args_position_targets():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["tool_contract"]["input_schema_json"]["properties"]["memberId"] = {
            "type": "string"
        }
        payload["execution_profile"]["args_position_json"] = {
            "customerId": {"in": "header", "name": "X-Actor-Id"},
            "memberId": {"in": "header", "name": "X-Actor-Id"},
        }

        response = client.post("/api/v1/gdp/http-assets", json=payload)

        assert response.status_code == 400
        assert "重复目标投递" in response.json()["detail"]
    finally:
        engine.dispose()


def test_create_rejects_request_template_method_get_with_body():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["request_template_json"] = {
            "method": "GET",
            "body": '{"customerId": "{{ args.customerId }}"}',
        }

        response = client.post("/api/v1/gdp/http-assets", json=payload)

        assert response.status_code == 400
        assert "GET 禁止 request_template_json.body" in response.json()["detail"]
    finally:
        engine.dispose()


def test_create_rejects_extra_path_route_target_not_in_url_placeholder():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["tool_contract"]["input_schema_json"]["properties"]["orderId"] = {
            "type": "string"
        }
        payload["execution_profile"]["direct_url"] = "https://api.example.com/users/{customer_id}"
        payload["execution_profile"]["args_position_json"] = {
            "customerId": {"in": "path", "name": "customer_id"},
            "orderId": {"in": "path", "name": "order_id"},
        }

        response = client.post("/api/v1/gdp/http-assets", json=payload)

        assert response.status_code == 400
        assert "path 映射目标未出现在 URL 占位符中" in response.json()["detail"]
    finally:
        engine.dispose()


def test_assemble_previews_runtime_request_with_json_body():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["direct_url"] = (
            "https://api.example.com/customers/{customer_id}/signup"
        )
        payload["execution_profile"]["args_position_json"] = {
            "customerId": {"in": "path", "name": "customer_id"},
            "traceId": {"in": "header", "name": "X-Trace-Id"},
        }
        payload["execution_profile"]["request_template_json"] = {
            "method": "POST",
            "argsToJsonBody": True,
        }
        payload["tool_contract"]["input_schema_json"]["properties"]["traceId"] = {
            "type": "string"
        }
        payload["tool_contract"]["input_schema_json"]["properties"]["channel"] = {
            "type": "string"
        }

        response = client.post(
            "/api/v1/gdp/http-assets/assemble",
            json={
                "payload": payload,
                "mock_args": {
                    "customerId": "C-1",
                    "traceId": "trace-1",
                    "channel": "wechat",
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "POST"
        assert (
            data["url"] == "https://api.example.com/customers/C-1/signup"
        )
        assert data["headers"]["X-Trace-Id"] == "trace-1"
        assert data["headers"]["Content-Type"] == "application/json"
        assert data["body"] == '{"channel": "wechat"}'
    finally:
        engine.dispose()


def test_normalize_builds_schema_and_routes_from_visual_tree():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["tool_contract"]["input_schema_json"] = {
            "type": "object",
            "properties": {},
        }
        payload["tool_contract"]["output_schema_json"] = {
            "type": "object",
            "properties": {},
        }
        payload["execution_profile"]["args_position_json"] = {}
        payload["execution_profile"]["direct_url"] = (
            "https://api.example.com/customers/{customer_id}/signup"
        )

        response = client.post(
            "/api/v1/gdp/http-assets/normalize",
            json={
                "payload": payload,
                "input_tree": [
                    {
                        "id": "customer",
                        "name": "customerId",
                        "type": "string",
                        "description": "客户编号",
                        "required": True,
                        "route": {"in": "path", "name": "customer_id"},
                    },
                    {
                        "id": "trace",
                        "name": "traceId",
                        "type": "string",
                        "description": "链路追踪号",
                        "required": False,
                        "route": {"in": "header", "name": "X-Trace-Id"},
                    },
                ],
                "output_tree": [
                    {
                        "id": "signup",
                        "name": "signupId",
                        "type": "string",
                        "description": "报名单号",
                        "required": False,
                    }
                ],
            },
        )

        assert response.status_code == 200
        normalized = response.json()["payload"]
        assert normalized["tool_contract"]["input_schema_json"] == {
            "type": "object",
            "properties": {
                "customerId": {
                    "type": "string",
                    "description": "客户编号",
                },
                "traceId": {
                    "type": "string",
                    "description": "链路追踪号",
                },
            },
            "required": ["customerId"],
        }
        assert normalized["execution_profile"]["args_position_json"] == {
            "customerId": {"in": "path", "name": "customer_id"},
            "traceId": {"in": "header", "name": "X-Trace-Id"},
        }
        assert normalized["tool_contract"]["output_schema_json"] == {
            "type": "object",
            "properties": {
                "signupId": {
                    "type": "string",
                    "description": "报名单号",
                }
            },
            "required": [],
        }
    finally:
        engine.dispose()


def test_normalize_rejects_same_invalid_visual_mapping_as_runtime_validator():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["tool_contract"]["input_schema_json"] = {
            "type": "object",
            "properties": {},
        }
        payload["execution_profile"]["args_position_json"] = {}

        response = client.post(
            "/api/v1/gdp/http-assets/normalize",
            json={
                "payload": payload,
                "input_tree": [
                    {
                        "id": "customer",
                        "name": "customerId",
                        "type": "string",
                        "description": "客户编号",
                        "required": True,
                        "route": {"in": "path", "name": "customer_id"},
                    }
                ],
            },
        )

        assert response.status_code == 400
        assert "URL 无占位符时不能配置 path 路由" in response.json()["detail"]
    finally:
        engine.dispose()


def test_assemble_previews_plain_text_body_and_redacts_auth_header():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["request_template_json"] = {
            "method": "POST",
            "headers": [
                {"key": "Content-Type", "value": "text/plain; charset=utf-8"},
            ],
            "body": "customer={{ args.customerId }}",
        }
        payload["execution_profile"]["auth_json"] = {
            "type": "bearer",
            "token": "secret-token",
        }

        response = client.post(
            "/api/v1/gdp/http-assets/assemble",
            json={
                "payload": payload,
                "mock_args": {"customerId": "C-1"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "POST"
        assert data["headers"]["Content-Type"] == "text/plain; charset=utf-8"
        assert data["headers"]["Authorization"] == "Bearer ***"
        assert data["body"] == "customer=C-1"
    finally:
        engine.dispose()


def test_assemble_rejects_same_invalid_configuration_as_runtime_validator():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["request_template_json"] = {
            "method": "GET",
            "body": '{"customerId": "{{ args.customerId }}"}',
        }

        response = client.post(
            "/api/v1/gdp/http-assets/assemble",
            json={
                "payload": payload,
                "mock_args": {"customerId": "C-1"},
            },
        )

        assert response.status_code == 400
        assert "GET 禁止 request_template_json.body" in response.json()["detail"]
    finally:
        engine.dispose()


def test_assemble_supports_get_args_to_url_param_preview():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["method"] = "GET"
        payload["execution_profile"]["args_position_json"] = {}
        payload["execution_profile"]["request_template_json"] = {
            "method": "GET",
            "argsToUrlParam": True,
        }
        payload["tool_contract"]["input_schema_json"]["properties"]["page"] = {
            "type": "integer"
        }

        response = client.post(
            "/api/v1/gdp/http-assets/assemble",
            json={
                "payload": payload,
                "mock_args": {"customerId": "C-1", "page": 2},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["method"] == "GET"
        assert data["url"] == "https://api.example.com/signup?customerId=C-1&page=2"
        assert data["body"] is None
    finally:
        engine.dispose()


def test_assemble_supports_tag_mode_preview(monkeypatch):
    client, _, engine, _, _, _ = _build_client()
    try:
        monkeypatch.setenv(
            "XAGENT_GDP_HTTP_BASE_URL_CRM_PUBLIC",
            "https://gateway.example.com",
        )
        payload = _valid_payload()
        payload["execution_profile"]["url_mode"] = "tag"
        payload["execution_profile"]["direct_url"] = None
        payload["execution_profile"]["sys_label"] = "public"
        payload["execution_profile"]["url_suffix"] = "/signup/query"
        payload["execution_profile"]["method"] = "GET"
        payload["execution_profile"]["args_position_json"] = {}
        payload["execution_profile"]["request_template_json"] = {
            "method": "GET",
            "argsToUrlParam": True,
        }

        response = client.post(
            "/api/v1/gdp/http-assets/assemble",
            json={
                "payload": payload,
                "mock_args": {"customerId": "C-1"},
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["url"] == "https://gateway.example.com/signup/query?customerId=C-1"
        assert data["method"] == "GET"
    finally:
        engine.dispose()


def test_assemble_supports_query_object_style_flatten_preview():
    client, _, engine, _, _, _ = _build_client()
    try:
        payload = _valid_payload()
        payload["execution_profile"]["method"] = "GET"
        payload["execution_profile"]["args_position_json"] = {
            "filters": {"in": "query", "name": "filters", "objectStyle": "flatten"},
        }
        payload["execution_profile"]["request_template_json"] = {"method": "GET"}
        payload["tool_contract"]["input_schema_json"]["properties"]["filters"] = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "region": {
                    "type": "object",
                    "properties": {"code": {"type": "string"}},
                },
            },
        }

        response = client.post(
            "/api/v1/gdp/http-assets/assemble",
            json={
                "payload": payload,
                "mock_args": {
                    "filters": {"status": "active", "region": {"code": "cn"}},
                },
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert (
            data["url"]
            == "https://api.example.com/signup?filters.status=active&filters.region.code=cn"
        )
    finally:
        engine.dispose()
