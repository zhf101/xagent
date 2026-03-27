"""资产校验器。"""

from __future__ import annotations


def validate_asset_common(payload: dict) -> None:
    name = str(payload.get("name") or "").strip()
    system_short = str(payload.get("system_short") or "").strip()

    if not name:
        raise ValueError("name is required")
    if not system_short:
        raise ValueError("system_short is required")


def validate_sql_asset_payload(payload: dict, datasource=None) -> None:
    validate_asset_common(payload)
    if datasource is None:
        raise ValueError("datasource_asset_id is required")
    if str(payload.get("system_short")) != str(getattr(datasource, "system_short", "")):
        raise ValueError("system_short must match datasource")
    config = payload.get("config") or {}
    sql_kind = str(config.get("sql_kind") or "").strip().lower()
    if sql_kind and sql_kind not in {"select", "insert", "update", "delete", "ddl"}:
        raise ValueError("config.sql_kind is invalid")


def validate_http_asset_payload(payload: dict) -> None:
    validate_asset_common(payload)
    config = payload.get("config") or {}
    base_url = str(config.get("base_url") or "").strip()
    path_template = str(config.get("path_template") or "").strip()
    method = str(config.get("method") or "").strip().upper()
    if not base_url:
        raise ValueError("config.base_url is required")
    if not path_template:
        raise ValueError("config.path_template is required")
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("config.method is invalid")


def validate_dubbo_asset_payload(payload: dict) -> None:
    validate_asset_common(payload)
    config = payload.get("config") or {}
    service_interface = str(config.get("service_interface") or "").strip()
    method_name = str(config.get("method_name") or "").strip()
    registry = str(config.get("registry") or "").strip()
    if not service_interface:
        raise ValueError("config.service_interface is required")
    if not method_name:
        raise ValueError("config.method_name is required")
    if not registry:
        raise ValueError("config.registry is required")
