"""Vanna 知识库宿主服务。

这个模块管理的是“知识应该挂在哪个 kb 下”这一层边界。
它不负责训练、检索或执行，只负责把 datasource 与知识库宿主关系稳定下来。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from xagent.gdp.vanna.adapter.database.config import clean_database_name, resolve_database_name_from_url
from xagent.gdp.vanna.model.text2sql import Text2SQLDatabase
from xagent.gdp.vanna.model.vanna import VannaKnowledgeBase, VannaKnowledgeBaseStatus
from .errors import VannaDatasourceNotFoundError, VannaKnowledgeBaseNotFoundError


class KnowledgeBaseService:
    """管理 Vanna 知识库宿主。

    知识库在这里扮演“一个 datasource 的 AI 治理容器”：
    - 挂住 datasource 基本信息
    - 挂住 schema / 训练条目 / ask 记录 / SQL 资产
    - 提供 owner 级别的隔离
    """

    def __init__(self, db: Session):
        self.db = db

    def _get_datasource(
        self,
        *,
        datasource_id: int,
        owner_user_id: int | None = None,
    ) -> Text2SQLDatabase:
        """读取数据源，并在需要时校验所属用户。"""

        query = self.db.query(Text2SQLDatabase).filter(
            Text2SQLDatabase.id == int(datasource_id)
        )
        if owner_user_id is not None:
            query = query.filter(Text2SQLDatabase.user_id == int(owner_user_id))
        datasource = query.first()
        if datasource is None:
            raise VannaDatasourceNotFoundError(
                f"Datasource {datasource_id} was not found"
            )
        return datasource

    def _resolve_datasource_database_name(self, datasource: Text2SQLDatabase) -> str | None:
        """尽量为 datasource 推导出稳定的 database_name。

        这个值后续会影响 SQL 资产复用与执行校验，因此这里优先保证稳定一致，
        而不是追求展示层的花样格式。
        """

        return clean_database_name(datasource.database_name) or resolve_database_name_from_url(
            str(datasource.url)
        )

    def get_or_create_default_kb(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        owner_user_name: str | None = None,
    ) -> VannaKnowledgeBase:
        """获取或创建默认知识库。

        当前产品策略是“每个 datasource 自动对应一个默认 KB”，
        这样前端不需要多一步初始化动作。
        """

        datasource = self._get_datasource(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
        )
        kb_code = f"vanna.ds{int(datasource.id)}.default"
        kb = (
            self.db.query(VannaKnowledgeBase)
            .filter(VannaKnowledgeBase.kb_code == kb_code)
            .first()
        )
        if kb is not None:
            # 现有默认 kb 不重建，只做必要字段同步，避免下游 schema / 训练条目丢失归属。
            changed = False
            for field_name, value in (
                ("owner_user_name", owner_user_name),
                ("datasource_name", datasource.name),
                ("system_short", datasource.system_short),
                ("database_name", self._resolve_datasource_database_name(datasource)),
                ("env", datasource.env),
                ("db_type", datasource.type.value),
                ("dialect", datasource.type.value),
            ):
                if getattr(kb, field_name) != value and value is not None:
                    setattr(kb, field_name, value)
                    changed = True
            if changed:
                self.db.commit()
                self.db.refresh(kb)
            return kb

        kb = VannaKnowledgeBase(
            kb_code=kb_code,
            name=f"{datasource.name}-default",
            owner_user_id=int(owner_user_id),
            owner_user_name=owner_user_name,
            datasource_id=int(datasource.id),
            datasource_name=datasource.name,
            system_short=datasource.system_short,
            database_name=self._resolve_datasource_database_name(datasource),
            env=datasource.env,
            db_type=datasource.type.value,
            dialect=datasource.type.value,
            status=VannaKnowledgeBaseStatus.ACTIVE.value,
        )
        self.db.add(kb)
        self.db.commit()
        self.db.refresh(kb)
        return kb

    def list_kbs(
        self,
        *,
        owner_user_id: int | None = None,
        datasource_id: int | None = None,
    ) -> list[VannaKnowledgeBase]:
        """按用户/数据源过滤知识库列表。"""

        query = self.db.query(VannaKnowledgeBase)
        if owner_user_id is not None:
            query = query.filter(VannaKnowledgeBase.owner_user_id == int(owner_user_id))
        if datasource_id is not None:
            query = query.filter(VannaKnowledgeBase.datasource_id == int(datasource_id))
        return query.order_by(VannaKnowledgeBase.created_at.desc()).all()

    def get_kb(
        self,
        *,
        kb_id: int,
        owner_user_id: int | None = None,
    ) -> VannaKnowledgeBase:
        """读取单个知识库，并在需要时校验归属。"""

        query = self.db.query(VannaKnowledgeBase).filter(
            VannaKnowledgeBase.id == int(kb_id)
        )
        if owner_user_id is not None:
            query = query.filter(VannaKnowledgeBase.owner_user_id == int(owner_user_id))
        kb = query.first()
        if kb is None:
            raise VannaKnowledgeBaseNotFoundError(
                f"Knowledge base {kb_id} was not found"
            )
        return kb

