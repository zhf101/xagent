"""Datamakepool asset repositories."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.datamakepool_asset import DataMakepoolAsset


class HttpAssetRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_http_assets(
        self,
        system_short: str | None = None,
        status: str | None = None,
    ) -> list[DataMakepoolAsset]:
        query = self.db.query(DataMakepoolAsset).filter(
            DataMakepoolAsset.asset_type == "http",
        )
        if system_short:
            query = query.filter(DataMakepoolAsset.system_short == system_short)
        if status:
            query = query.filter(DataMakepoolAsset.status == status)
        return query.order_by(DataMakepoolAsset.id.asc()).all()

    def list_active_http_assets(
        self,
        system_short: str | None = None,
    ) -> list[DataMakepoolAsset]:
        return self.list_http_assets(system_short=system_short, status="active")

    def get_by_id(self, asset_id: int) -> DataMakepoolAsset | None:
        return (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == asset_id)
            .first()
        )

    def create_http_asset(self, payload: dict[str, Any]) -> DataMakepoolAsset:
        asset = DataMakepoolAsset(
            name=payload["name"],
            asset_type="http",
            system_short=payload["system_short"],
            status=payload.get("status", "active"),
            description=payload.get("description"),
            config=payload.get("config") or {},
            sensitivity_level=payload.get("sensitivity_level"),
            version=payload.get("version", 1),
            created_by=payload.get("created_by"),
            updated_by=payload.get("updated_by"),
        )
        self.db.add(asset)
        self.db.flush()
        return asset

    def update_http_asset(
        self,
        asset: DataMakepoolAsset,
        payload: dict[str, Any],
    ) -> DataMakepoolAsset:
        asset.name = payload["name"]
        asset.system_short = payload["system_short"]
        asset.status = payload.get("status", asset.status)
        asset.description = payload.get("description")
        asset.config = payload.get("config") or {}
        asset.sensitivity_level = payload.get("sensitivity_level")
        asset.updated_by = payload.get("updated_by")
        asset.version = int(asset.version or 1) + 1
        self.db.flush()
        return asset

    def delete_http_asset(self, asset: DataMakepoolAsset) -> None:
        self.db.delete(asset)
        self.db.flush()


class SqlAssetRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_datasource_assets(
        self,
        system_short: str | None = None,
        status: str | None = "active",
    ) -> list[DataMakepoolAsset]:
        query = self.db.query(DataMakepoolAsset).filter(
            DataMakepoolAsset.asset_type == "datasource",
        )
        if system_short:
            query = query.filter(DataMakepoolAsset.system_short == system_short)
        if status:
            query = query.filter(DataMakepoolAsset.status == status)
        return query.order_by(DataMakepoolAsset.id.asc()).all()

    def list_sql_assets(
        self,
        system_short: str | None = None,
        status: str | None = None,
    ) -> list[DataMakepoolAsset]:
        query = self.db.query(DataMakepoolAsset).filter(
            DataMakepoolAsset.asset_type == "sql",
        )
        if system_short:
            query = query.filter(DataMakepoolAsset.system_short == system_short)
        if status:
            query = query.filter(DataMakepoolAsset.status == status)
        return query.order_by(DataMakepoolAsset.id.asc()).all()

    def list_active_sql_assets(
        self,
        system_short: str | None = None,
    ) -> list[DataMakepoolAsset]:
        return self.list_sql_assets(system_short=system_short, status="active")

    def get_by_id(self, asset_id: int) -> DataMakepoolAsset | None:
        return (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == asset_id)
            .first()
        )

    def get_datasource_asset(self, asset_id: int) -> DataMakepoolAsset | None:
        return (
            self.db.query(DataMakepoolAsset)
            .filter(
                DataMakepoolAsset.id == asset_id,
                DataMakepoolAsset.asset_type == "datasource",
            )
            .first()
        )

    def create_sql_asset(self, payload: dict[str, Any]) -> DataMakepoolAsset:
        asset = DataMakepoolAsset(
            name=payload["name"],
            asset_type="sql",
            system_short=payload["system_short"],
            status=payload.get("status", "active"),
            description=payload.get("description"),
            config=payload.get("config") or {},
            datasource_asset_id=payload.get("datasource_asset_id"),
            sensitivity_level=payload.get("sensitivity_level"),
            version=payload.get("version", 1),
            created_by=payload.get("created_by"),
            updated_by=payload.get("updated_by"),
        )
        self.db.add(asset)
        self.db.flush()
        return asset

    def update_sql_asset(
        self,
        asset: DataMakepoolAsset,
        payload: dict[str, Any],
    ) -> DataMakepoolAsset:
        asset.name = payload["name"]
        asset.system_short = payload["system_short"]
        asset.status = payload.get("status", asset.status)
        asset.description = payload.get("description")
        asset.config = payload.get("config") or {}
        asset.datasource_asset_id = payload.get("datasource_asset_id")
        asset.sensitivity_level = payload.get("sensitivity_level")
        asset.updated_by = payload.get("updated_by")
        asset.version = int(asset.version or 1) + 1
        self.db.flush()
        return asset

    def delete_sql_asset(self, asset: DataMakepoolAsset) -> None:
        self.db.delete(asset)
        self.db.flush()


class DubboAssetRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_dubbo_assets(
        self,
        system_short: str | None = None,
        status: str | None = None,
    ) -> list[DataMakepoolAsset]:
        query = self.db.query(DataMakepoolAsset).filter(
            DataMakepoolAsset.asset_type == "dubbo",
        )
        if system_short:
            query = query.filter(DataMakepoolAsset.system_short == system_short)
        if status:
            query = query.filter(DataMakepoolAsset.status == status)
        return query.order_by(DataMakepoolAsset.id.asc()).all()

    def list_active_dubbo_assets(
        self,
        system_short: str | None = None,
    ) -> list[DataMakepoolAsset]:
        return self.list_dubbo_assets(system_short=system_short, status="active")

    def get_by_id(self, asset_id: int) -> DataMakepoolAsset | None:
        return (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == asset_id)
            .first()
        )

    def create_dubbo_asset(self, payload: dict[str, Any]) -> DataMakepoolAsset:
        asset = DataMakepoolAsset(
            name=payload["name"],
            asset_type="dubbo",
            system_short=payload["system_short"],
            status=payload.get("status", "active"),
            description=payload.get("description"),
            config=payload.get("config") or {},
            sensitivity_level=payload.get("sensitivity_level"),
            version=payload.get("version", 1),
            created_by=payload.get("created_by"),
            updated_by=payload.get("updated_by"),
        )
        self.db.add(asset)
        self.db.flush()
        return asset

    def update_dubbo_asset(
        self,
        asset: DataMakepoolAsset,
        payload: dict[str, Any],
    ) -> DataMakepoolAsset:
        asset.name = payload["name"]
        asset.system_short = payload["system_short"]
        asset.status = payload.get("status", asset.status)
        asset.description = payload.get("description")
        asset.config = payload.get("config") or {}
        asset.sensitivity_level = payload.get("sensitivity_level")
        asset.updated_by = payload.get("updated_by")
        asset.version = int(asset.version or 1) + 1
        self.db.flush()
        return asset

    def delete_dubbo_asset(self, asset: DataMakepoolAsset) -> None:
        self.db.delete(asset)
        self.db.flush()
