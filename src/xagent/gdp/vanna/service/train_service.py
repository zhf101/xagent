"""Vanna 训练条目写入服务。"""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from xagent.gdp.vanna.model.vanna import (
    VannaSchemaTable,
    VannaSchemaTableStatus,
    VannaTrainingEntry,
    VannaTrainingLifecycleStatus,
    VannaTrainingQualityStatus,
)
from .knowledge_base_service import KnowledgeBaseService
from .schema_summary_service import SchemaSummaryService


class TrainService:
    """管理手工训练和 bootstrap_schema。

    这里处理的是“知识如何进入 Vanna”。
    和 ask/query 不同，train 更关注：
    - 训练条目的标准化
    - 去重
    - 生命周期初始状态
    """

    def __init__(self, db: Session):
        self.db = db
        self.kb_service = KnowledgeBaseService(db)
        self.schema_summary_service = SchemaSummaryService(db)

    def _hash_text(self, payload: str) -> str:
        """为训练内容生成稳定 hash。"""

        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def train_question_sql(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
        question: str,
        sql: str,
        publish: bool = True,
        sql_explanation: str | None = None,
    ) -> VannaTrainingEntry:
        """写入 question_sql 训练条目。

        一个典型样本形态是“自然语言问题 + 对应 SQL”。
        这是 ask 检索链最重要的一类基础知识。
        """

        kb = self.kb_service.get_or_create_default_kb(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
            owner_user_name=create_user_name,
        )
        content_hash = self._hash_text(f"{question}\n{sql}")
        entry_code = f"question-sql:{int(kb.id)}:{content_hash}"
        entry = (
            self.db.query(VannaTrainingEntry)
            .filter(VannaTrainingEntry.entry_code == entry_code)
            .first()
        )
        if entry is None:
            entry = VannaTrainingEntry(
                kb_id=int(kb.id),
                datasource_id=int(kb.datasource_id),
                system_short=kb.system_short,
                env=kb.env,
                entry_code=entry_code,
                entry_type="question_sql",
                source_kind="manual",
                lifecycle_status=(
                    VannaTrainingLifecycleStatus.PUBLISHED.value
                    if publish
                    else VannaTrainingLifecycleStatus.CANDIDATE.value
                ),
                quality_status=(
                    VannaTrainingQualityStatus.VERIFIED.value
                    if publish
                    else VannaTrainingQualityStatus.UNVERIFIED.value
                ),
                title=question[:255],
                question_text=question,
                sql_text=sql,
                sql_explanation=sql_explanation,
                create_user_id=int(owner_user_id),
                create_user_name=create_user_name,
                content_hash=content_hash,
            )
            self.db.add(entry)
        else:
            entry.question_text = question
            entry.sql_text = sql
            entry.sql_explanation = sql_explanation
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def train_documentation(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
        title: str,
        documentation: str,
        publish: bool = True,
    ) -> VannaTrainingEntry:
        """写入 documentation 训练条目。

        这类条目不直接给 SQL，而是补充业务背景、指标定义等文档事实。
        """

        kb = self.kb_service.get_or_create_default_kb(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
            owner_user_name=create_user_name,
        )
        content_hash = self._hash_text(f"{title}\n{documentation}")
        entry_code = f"documentation:{int(kb.id)}:{content_hash}"
        entry = (
            self.db.query(VannaTrainingEntry)
            .filter(VannaTrainingEntry.entry_code == entry_code)
            .first()
        )
        if entry is None:
            entry = VannaTrainingEntry(
                kb_id=int(kb.id),
                datasource_id=int(kb.datasource_id),
                system_short=kb.system_short,
                env=kb.env,
                entry_code=entry_code,
                entry_type="documentation",
                source_kind="manual",
                lifecycle_status=(
                    VannaTrainingLifecycleStatus.PUBLISHED.value
                    if publish
                    else VannaTrainingLifecycleStatus.CANDIDATE.value
                ),
                quality_status=(
                    VannaTrainingQualityStatus.VERIFIED.value
                    if publish
                    else VannaTrainingQualityStatus.UNVERIFIED.value
                ),
                title=title[:255],
                doc_text=documentation,
                create_user_id=int(owner_user_id),
                create_user_name=create_user_name,
                content_hash=content_hash,
            )
            self.db.add(entry)
        else:
            entry.doc_text = documentation
            entry.title = title[:255]
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def bootstrap_schema(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        create_user_name: str | None,
    ) -> list[VannaTrainingEntry]:
        """把已采集 schema 批量转成候选训练条目。

        适合冷启动场景：还没有人工整理 question/sql 时，
        先把 schema 摘要喂给系统，保证检索层至少有基础结构知识。
        """

        kb = self.kb_service.get_or_create_default_kb(
            datasource_id=datasource_id,
            owner_user_id=owner_user_id,
            owner_user_name=create_user_name,
        )
        table_rows = (
            self.db.query(VannaSchemaTable)
            .filter(
                VannaSchemaTable.kb_id == int(kb.id),
                VannaSchemaTable.status == VannaSchemaTableStatus.ACTIVE.value,
            )
            .order_by(
                VannaSchemaTable.schema_name.asc(), VannaSchemaTable.table_name.asc()
            )
            .all()
        )
        return [
            self.schema_summary_service.create_schema_summary_entry(
                table_row=table_row,
                create_user_id=int(owner_user_id),
                create_user_name=create_user_name,
                lifecycle_status=VannaTrainingLifecycleStatus.CANDIDATE.value,
                quality_status=VannaTrainingQualityStatus.UNVERIFIED.value,
            )
            for table_row in table_rows
        ]

