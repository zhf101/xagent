from __future__ import annotations

import tempfile
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.api.system_registry import router as system_registry_router
from xagent.web.api.text2sql import text2sql_router
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
    requester = User(username="requester", password_hash="hashed", is_admin=False)
    approver = User(username="approver", password_hash="hashed", is_admin=False)
    outsider = User(username="outsider", password_hash="hashed", is_admin=False)
    db.add_all([requester, approver, outsider])
    db.commit()
    db.refresh(requester)
    db.refresh(approver)
    db.refresh(outsider)
    db.add(
        SystemRegistry(
            system_short="CRM",
            display_name="CRM",
            status="active",
            created_by=int(approver.id),
        )
    )
    db.add(
        UserSystemRole(
            user_id=int(approver.id),
            system_short="CRM",
            role="system_admin",
            granted_by=int(approver.id),
        )
    )
    db.commit()
    db.close()

    app = FastAPI()
    app.include_router(system_registry_router)
    app.include_router(text2sql_router)

    current_user = {"value": requester}

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

    return TestClient(app), SessionLocal, engine, requester, approver, outsider, set_current_user


def test_datasource_request_submit_and_approve_by_system_admin():
    client, _, engine, requester, approver, outsider, set_current_user = _build_client()
    try:
        create_response = client.post(
            "/api/text2sql/databases",
            json={
                "name": "crm_sqlite",
                "system_short": "crm",
                "env": "prod",
                "type": "sqlite",
                "connection_mode": "url",
                "url": "sqlite:///crm.db",
                "connection_form": {},
                "read_only": True,
            },
        )
        assert create_response.status_code == 200
        request_payload = create_response.json()["data"]
        request_id = int(request_payload["id"])
        assert request_payload["status"] == "pending_approval"
        assert request_payload["system_short"] == "CRM"

        my_requests_response = client.get("/api/asset-change-requests/my")
        assert my_requests_response.status_code == 200
        assert len(my_requests_response.json()["data"]) == 1

        visible_before_approval = client.get("/api/text2sql/databases")
        assert visible_before_approval.status_code == 200
        assert visible_before_approval.json() == []

        set_current_user(outsider)
        outsider_queue = client.get("/api/approval-queue")
        assert outsider_queue.status_code == 200
        assert outsider_queue.json()["data"] == []

        set_current_user(approver)
        queue_response = client.get("/api/approval-queue")
        assert queue_response.status_code == 200
        queue_items = queue_response.json()["data"]
        assert len(queue_items) == 1
        assert queue_items[0]["id"] == request_id

        approve_response = client.post(
            f"/api/asset-change-requests/{request_id}/approve",
            json={"comment": "looks good"},
        )
        assert approve_response.status_code == 200
        assert approve_response.json()["data"]["status"] == "approved"

        databases_response = client.get("/api/text2sql/databases")
        assert databases_response.status_code == 200
        databases = databases_response.json()
        assert len(databases) == 1
        assert databases[0]["name"] == "crm_sqlite"
        assert databases[0]["system_short"] == "CRM"
        assert databases[0]["env"] == "prod"
        assert databases[0]["type"] == "sqlite"
        assert databases[0]["status"] == "disconnected"

        set_current_user(requester)
        detail_response = client.get(f"/api/asset-change-requests/{request_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()["data"]
        assert detail["status"] == "approved"
        assert detail["permissions"]["can_view"] is True
        assert detail["permissions"]["can_cancel"] is False
    finally:
        engine.dispose()
