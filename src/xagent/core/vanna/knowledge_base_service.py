"""Vanna 知识库宿主服务。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...web.models.text2sql import Text2SQLDatabase
from ...web.models.vanna import VannaKnowledgeBase, VannaKnowledgeBaseStatus
from .errors import VannaDatasourceNotFoundError, VannaKnowledgeBaseNotFoundError


class KnowledgeBaseService:
    """管理 Vanna 知识库宿主。"""

    def __init__(self, db: Session):
        self.db = db

    def _get_datasource(
        self,
        *,
        datasource_id: int,
        owner_user_id: int | None = None,
    ) -> Text2SQLDatabase:
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

    def get_or_create_default_kb(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        owner_user_name: str | None = None,
    ) -> VannaKnowledgeBase:
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
            changed = False
            for field_name, value in (
                ("owner_user_name", owner_user_name),
                ("datasource_name", datasource.name),
                ("system_short", datasource.system_short),
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
