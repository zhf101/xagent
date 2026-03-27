"""Datamakepool 资产仓储层。

这一层只负责把 `DataMakepoolAsset` 的数据库读写封装成按类型分组的接口，
避免 API / service 里反复散落 `asset_type` 过滤条件。

设计取舍：
- 仍然共用一张资产表，但仓储按 `http/sql/dubbo/datasource` 分开暴露方法
- 不在仓储层做复杂校验，校验交给 validator / service，仓储保持薄而稳定
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from xagent.web.models.text2sql import Text2SQLDatabase
from xagent.web.models.datamakepool_asset import DataMakepoolAsset


class HttpAssetRepository:
    """HTTP 资产仓储。"""

    def __init__(self, db: Session):
        self.db = db

    def list_http_assets(
        self,
        system_short: str | None = None,
        status: str | None = None,
    ) -> list[DataMakepoolAsset]:
        """列出 HTTP 资产。

        仅按类型、系统、状态做过滤，不承担权限裁剪和配置合法性判断。
        """

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
        """返回运行时可参与匹配的 HTTP 资产。"""

        return self.list_http_assets(system_short=system_short, status="active")

    def get_by_id(self, asset_id: int) -> DataMakepoolAsset | None:
        """按主键读取资产，不额外校验类型。"""

        return (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == asset_id)
            .first()
        )

    def create_http_asset(self, payload: dict[str, Any]) -> DataMakepoolAsset:
        """创建 HTTP 资产并 flush，事务提交仍由上层控制。"""

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

    def list_active_http_asset_ids_by_method(
        self,
        method: str,
        system_short: str | None = None,
    ) -> set[int]:
        """按 method 粗筛活跃 HTTP 资产 ID，用于规则候选并集。"""

        assets = self.list_active_http_assets(system_short=system_short)
        method_upper = str(method or "").upper()
        matched_ids: set[int] = set()
        for asset in assets:
            config = asset.config or {}
            asset_method = str(config.get("method") or "").upper()
            if not asset_method or asset_method == method_upper:
                matched_ids.add(int(asset.id))
        return matched_ids

    def update_http_asset(
        self,
        asset: DataMakepoolAsset,
        payload: dict[str, Any],
    ) -> DataMakepoolAsset:
        """更新 HTTP 资产定义并递增版本号。

        版本号递增代表“资产契约已变化”，方便前端和审计识别。
        """

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
        """删除资产实体并 flush。"""

        self.db.delete(asset)
        self.db.flush()


class SqlAssetRepository:
    """SQL / datasource 资产仓储。"""

    def __init__(self, db: Session):
        self.db = db

    def list_datasource_assets(
        self,
        system_short: str | None = None,
        status: str | None = "active",
    ) -> list[DataMakepoolAsset]:
        """列出数据源资产。

        数据源资产是 SQL 资产的宿主连接定义，因此单独保留查询入口。
        """

        query = self.db.query(DataMakepoolAsset).filter(
            DataMakepoolAsset.asset_type == "datasource",
        )
        if system_short:
            query = query.filter(DataMakepoolAsset.system_short == system_short)
        if status:
            query = query.filter(DataMakepoolAsset.status == status)
        return query.order_by(DataMakepoolAsset.id.asc()).all()

    def get_synced_datasource_asset_for_text2sql_database(
        self,
        text2sql_database_id: int,
    ) -> DataMakepoolAsset | None:
        """根据 Text2SQL 数据源 ID 查找已同步的 datasource 资产。"""

        candidates = (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.asset_type == "datasource")
            .order_by(DataMakepoolAsset.id.asc())
            .all()
        )
        for asset in candidates:
            config = asset.config or {}
            if config.get("source_type") != "text2sql_database":
                continue
            if int(config.get("source_database_id") or 0) == text2sql_database_id:
                return asset
        return None

    def upsert_datasource_asset_from_text2sql_database(
        self,
        database: Text2SQLDatabase,
        *,
        updated_by: int | None = None,
    ) -> DataMakepoolAsset:
        """把 Text2SQL 数据源同步为 datamakepool datasource 资产。

        这样 SQL 资产页面可以直接复用你已经在“数据源配置”里创建的连接定义，
        不需要要求用户再额外维护一套 datasource 资产。
        """

        asset = self.get_synced_datasource_asset_for_text2sql_database(int(database.id))
        config = {
            "source_type": "text2sql_database",
            "source_database_id": int(database.id),
            "db_type": database.type.value if database.type else None,
            "url": database.url,
            "read_only": bool(database.read_only),
            "enabled": bool(database.enabled),
        }
        status = "active" if bool(database.enabled) else "disabled"
        description = f"同步自 Text2SQL 数据源：{database.name}"
        system_short = str(getattr(database.system, "system_short", "") or "").strip()

        if asset is None:
            asset = DataMakepoolAsset(
                name=database.name,
                asset_type="datasource",
                system_short=system_short,
                status=status,
                description=description,
                config=config,
                created_by=updated_by,
                updated_by=updated_by,
                version=1,
            )
            self.db.add(asset)
            self.db.flush()
            return asset

        asset.name = database.name
        asset.system_short = system_short
        asset.status = status
        asset.description = description
        asset.config = config
        asset.updated_by = updated_by
        asset.version = int(asset.version or 1) + 1
        self.db.flush()
        return asset

    def list_sql_assets(
        self,
        system_short: str | None = None,
        status: str | None = None,
    ) -> list[DataMakepoolAsset]:
        """列出 SQL 资产。"""

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
        """返回运行时可被 matcher / resolver 选择的 SQL 资产。"""

        return self.list_sql_assets(system_short=system_short, status="active")

    def list_popular_active_sql_asset_ids(
        self,
        system_short: str | None = None,
        limit: int = 5,
    ) -> set[int]:
        """返回一小批热门 SQL 资产 ID，作为粗召回兜底候选。"""

        assets = self.list_active_sql_assets(system_short=system_short)
        return {int(asset.id) for asset in assets[: max(limit, 0)]}

    def get_by_id(self, asset_id: int) -> DataMakepoolAsset | None:
        """按主键读取任意资产。"""

        return (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == asset_id)
            .first()
        )

    def get_datasource_asset(self, asset_id: int) -> DataMakepoolAsset | None:
        """读取数据源资产，避免 SQL 资产误绑到非 datasource 资产。"""

        return (
            self.db.query(DataMakepoolAsset)
            .filter(
                DataMakepoolAsset.id == asset_id,
                DataMakepoolAsset.asset_type == "datasource",
            )
            .first()
        )

    def create_sql_asset(self, payload: dict[str, Any]) -> DataMakepoolAsset:
        """创建 SQL 资产并记录其 datasource 依赖。"""

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
        """更新 SQL 资产定义并同步提升版本号。"""

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
        """删除 SQL 资产。"""

        self.db.delete(asset)
        self.db.flush()


class DubboAssetRepository:
    """Dubbo 资产仓储。"""

    def __init__(self, db: Session):
        self.db = db

    def list_dubbo_assets(
        self,
        system_short: str | None = None,
        status: str | None = None,
    ) -> list[DataMakepoolAsset]:
        """列出 Dubbo 资产。"""

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
        """返回状态为 active 的 Dubbo 资产。"""

        return self.list_dubbo_assets(system_short=system_short, status="active")

    def get_by_id(self, asset_id: int) -> DataMakepoolAsset | None:
        """按主键读取资产。"""

        return (
            self.db.query(DataMakepoolAsset)
            .filter(DataMakepoolAsset.id == asset_id)
            .first()
        )

    def create_dubbo_asset(self, payload: dict[str, Any]) -> DataMakepoolAsset:
        """创建 Dubbo 资产。"""

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
        """更新 Dubbo 资产并递增版本号。"""

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
        """删除 Dubbo 资产。"""

        self.db.delete(asset)
        self.db.flush()
