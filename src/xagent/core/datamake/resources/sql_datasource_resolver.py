"""
`Resource Plane / SQL Datasource Resolver`（资源平面 / SQL 数据源解析器）模块。

所属分层：
- 代码分层：`src/xagent/core/datamake/resources`
- 架构分层：`Resource Plane`（资源平面）
- 在你的设计里：SQL 资源配置解析辅助件

这个文件负责什么：
- 解析 SQL 资源动作里声明的 datasource / database 引用
- 把显式参数、资源元数据、Text2SQL 数据源记录统一收敛成一份技术配置
- 为 SQL Brain、schema provider、runtime 适配器提供可复用的数据源事实

这个文件不负责什么：
- 不做 SQL 生成
- 不做审批
- 不做业务决策
- 不直接执行 SQL

设计原则：
- 优先使用显式传入参数
- 再看资源 metadata
- 最后按 datasource id / text2sql database id 去查宿主表
- 采用延迟导入，避免 core/datamake 在模块加载时强绑定 web 层
"""

from __future__ import annotations

from typing import Any, Mapping

from .sql_resource_definition import parse_sql_resource_metadata


class SqlDatasourceResolver:
    """
    `SqlDatasourceResolver`（SQL 数据源解析器）。

    当前 Phase 1 的目标很保守：
    - 先支持从 `Text2SQLDatabase`（Text2SQL 数据库配置）里解析出
      `db_url / db_type / read_only / datasource_name`
    - 后面若接 OpenViking 或统一 datasource 平台，只需要替换这里
      的解析实现，不需要重写 Guard / Runtime 主链
    """

    def resolve(
        self,
        *,
        metadata: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        解析当前 SQL 动作可见的数据源配置。

        返回值只承载技术事实，不承载“下一步业务动作”。
        """

        metadata = metadata or {}
        params = params or {}

        explicit = self._resolve_explicit_values(metadata=metadata, params=params)
        datasource_id = self._resolve_datasource_id(metadata=metadata, params=params)
        if datasource_id is None:
            return explicit

        loaded = self._load_text2sql_database(datasource_id)
        if not loaded:
            return explicit

        merged = dict(loaded)
        merged.update({k: v for k, v in explicit.items() if v is not None})
        return merged

    def _resolve_explicit_values(
        self,
        *,
        metadata: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """
        收敛显式声明的 datasource 技术字段。
        """

        parsed = parse_sql_resource_metadata(metadata)
        return {
            "connection_name": self._coalesce_str(
                params.get("connection_name"),
                parsed.datasource.connection_name,
            ),
            "db_url": self._coalesce_str(
                params.get("db_url"),
                params.get("database_url"),
                parsed.datasource.db_url,
            ),
            "db_type": self._coalesce_str(
                params.get("db_type"),
                params.get("database_type"),
                parsed.datasource.db_type,
            ),
            "read_only": self._coalesce_bool(
                params.get("read_only"),
                parsed.datasource.read_only,
            ),
            "datasource_name": self._coalesce_str(
                params.get("database_name"),
                parsed.datasource.datasource_name,
            ),
            "source": "inline",
        }

    def _resolve_datasource_id(
        self,
        *,
        metadata: Mapping[str, Any],
        params: Mapping[str, Any],
    ) -> int | None:
        """
        解析 datasource / text2sql database 的标识。
        """

        parsed = parse_sql_resource_metadata(metadata)
        candidates = [
            params.get("text2sql_database_id"),
            params.get("database_id"),
            params.get("datasource_id"),
            parsed.datasource.text2sql_database_id,
            parsed.datasource.datasource_id,
        ]
        for candidate in candidates:
            if isinstance(candidate, int):
                return candidate
            if isinstance(candidate, str) and candidate.strip().isdigit():
                return int(candidate.strip())
        return None

    def _load_text2sql_database(self, database_id: int) -> dict[str, Any]:
        """
        从宿主 `text2sql_databases` 表读取数据源配置。

        这里采用延迟导入和失败降级：
        - 如果 web 层 DB 未初始化，返回空
        - 如果表不存在或记录不存在，返回空
        - 不把宿主错误直接放大成 datamake 模块导入失败
        """

        try:
            from xagent.web.models.database import get_session_local
            from xagent.web.models.text2sql import Text2SQLDatabase
        except Exception:
            return {}

        try:
            session_local = get_session_local()
        except Exception:
            return {}

        with session_local() as session:
            database = (
                session.query(Text2SQLDatabase)
                .filter(Text2SQLDatabase.id == database_id)
                .first()
            )
            if database is None:
                return {}
            return {
                "datasource_id": database.id,
                "datasource_name": str(database.name or "").strip() or None,
                "db_url": str(database.url or "").strip() or None,
                "db_type": getattr(database.type, "value", None) or str(database.type),
                "read_only": bool(database.read_only),
                "source": "text2sql_database",
            }

    def _coalesce_str(self, *values: Any) -> str | None:
        """
        返回第一个非空字符串。
        """

        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _coalesce_bool(self, *values: Any) -> bool | None:
        """
        返回第一个显式布尔值。
        """

        for value in values:
            if isinstance(value, bool):
                return value
        return None
