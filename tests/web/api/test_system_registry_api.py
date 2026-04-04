from __future__ import annotations

import tempfile
from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from xagent.web.api.system_registry import router as system_registry_router
from xagent.web.auth_dependencies import get_current_user
from xagent.web.models.database import Base, get_db
from xagent.web.models.system_approval import SystemRegistry
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
    admin = User(username="admin", password_hash="hashed", is_admin=True)
    alice = User(username="alice", password_hash="hashed", is_admin=False)
    bob = User(username="bob", password_hash="hashed", is_admin=False)
    db.add_all([admin, alice, bob])
    db.commit()
    db.refresh(admin)
    db.refresh(alice)
    db.refresh(bob)
    db.close()

    app = FastAPI()
    app.include_router(system_registry_router)

    current_user = {"value": admin}

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

    return TestClient(app), SessionLocal, engine, admin, alice, bob, set_current_user


def test_admin_can_manage_system_registry_and_roles():
    client, _, engine, _, alice, _, _ = _build_client()
    try:
        create_response = client.post(
            "/api/system-registry",
            json={
                "system_short": "crm",
                "display_name": "CRM System",
                "description": "customer relationship management",
            },
        )
        assert create_response.status_code == 200
        assert create_response.json()["data"]["system_short"] == "CRM"

        role_response = client.post(
            "/api/system-registry/CRM/members",
            json={"user_id": int(alice.id), "role": "system_admin"},
        )
        assert role_response.status_code == 200
        assert role_response.json()["data"]["role"] == "system_admin"

        members_response = client.get("/api/system-registry/CRM/members")
        assert members_response.status_code == 200
        members = members_response.json()["data"]
        assert len(members) == 1
        assert members[0]["username"] == "alice"
        assert members[0]["role"] == "system_admin"

        update_response = client.put(
            "/api/system-registry/CRM",
            json={
                "display_name": "CRM Core",
                "description": "updated",
                "status": "disabled",
            },
        )
        assert update_response.status_code == 200
        payload = update_response.json()["data"]
        assert payload["display_name"] == "CRM Core"
        assert payload["status"] == "disabled"
    finally:
        engine.dispose()


def test_non_admin_cannot_manage_system_registry():
    client, SessionLocal, engine, admin, alice, _, set_current_user = _build_client()
    try:
        db = SessionLocal()
        db.add(
            SystemRegistry(
                system_short="CRM",
                display_name="CRM",
                status="active",
                created_by=int(admin.id),
            )
        )
        db.commit()
        db.close()

        set_current_user(alice)

        create_response = client.post(
            "/api/system-registry",
            json={"system_short": "erp", "display_name": "ERP"},
        )
        assert create_response.status_code == 403

        members_response = client.get("/api/system-registry/CRM/members")
        assert members_response.status_code == 403
    finally:
        engine.dispose()
