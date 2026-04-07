# System Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `system_short`-centric system registry, system role management, and approval-driven asset change workflows for datasource and GDP HTTP assets.

**Architecture:** Keep runtime SQL approval untouched and add a parallel asset-change approval stack centered on `system_short` as the natural key. Formalize system ownership in dedicated tables, route write operations into approval requests, and project approved changes into the existing asset tables.

**Tech Stack:** FastAPI, SQLAlchemy ORM, Alembic, pytest, existing Xagent web models and services.

---

### Task 1: Persistence Layer

**Files:**
- Create: `src/xagent/web/models/system_approval.py`
- Modify: `src/xagent/web/models/__init__.py`
- Modify: `src/xagent/web/models/database.py`
- Create: `src/xagent/migrations/versions/20260404_add_system_asset_approval_tables.py`

- [ ] Add `SystemRegistry`, `UserSystemRole`, `AssetChangeRequest`, `AssetChangeRequestLog` ORM models.
- [ ] Register the new models in model exports and DB init imports.
- [ ] Add Alembic migration for new tables and supporting indexes.

### Task 2: Shared Authorization and Registry APIs

**Files:**
- Create: `src/xagent/web/services/system_approval_service.py`
- Create: `src/xagent/web/api/system_registry.py`
- Modify: `src/xagent/web/app.py`

- [ ] Add helpers for `is_global_admin`, `has_system_role`, and approval routing.
- [ ] Add CRUD-lite APIs for system registry and system member roles.
- [ ] Mount the new router in the app.

### Task 3: Datasource Approval Flow

**Files:**
- Modify: `src/xagent/web/models/text2sql.py`
- Modify: `src/xagent/web/api/text2sql.py`

- [ ] Add approval metadata columns to datasource model.
- [ ] Convert create/update/delete write endpoints into asset change request creation.
- [ ] Add approval queue endpoints that can approve datasource requests and project them into `text2sql_databases`.

### Task 4: GDP HTTP Approval Flow

**Files:**
- Modify: `src/xagent/web/models/gdp_http_resource.py`
- Modify: `src/xagent/web/api/gdp_http_assets.py`
- Modify: `src/xagent/core/gdp/application/http_resource_service.py`

- [ ] Add approval metadata columns to GDP HTTP assets.
- [ ] Convert create/update/delete routes into asset change request creation.
- [ ] Reuse the shared approval projector to apply approved GDP HTTP requests.

### Task 5: Targeted Tests

**Files:**
- Create: `tests/web/api/test_system_registry_api.py`
- Create: `tests/web/api/test_asset_change_requests_api.py`
- Modify: `tests/web/api/test_gdp_http_assets.py`

- [ ] Cover system registry and role assignment permissions.
- [ ] Cover datasource approval request submission and approval.
- [ ] Cover GDP HTTP asset submission replacing direct writes.
