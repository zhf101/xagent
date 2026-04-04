"""Vanna SQL Asset 管理服务。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ....web.models.vanna import (
    VannaAskRun,
    VannaSqlAsset,
    VannaSqlAssetQualityStatus,
    VannaSqlAssetStatus,
    VannaSqlAssetVersion,
    VannaTrainingEntry,
)
from ..knowledge_base_service import KnowledgeBaseService


class SqlAssetService:
    """管理 SQL Asset、版本与 ask/train 提升。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.kb_service = KnowledgeBaseService(db)

    def _resolve_kb(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        owner_user_name: str | None,
        kb_id: int | None,
    ):
        if kb_id is not None:
            return self.kb_service.get_kb(
                kb_id=int(kb_id), owner_user_id=int(owner_user_id)
            )
        return self.kb_service.get_or_create_default_kb(
            datasource_id=int(datasource_id),
            owner_user_id=int(owner_user_id),
            owner_user_name=owner_user_name,
        )

    def _get_owned_asset(self, *, asset_id: int, owner_user_id: int) -> VannaSqlAsset:
        asset = (
            self.db.query(VannaSqlAsset)
            .filter(
                VannaSqlAsset.id == int(asset_id),
                VannaSqlAsset.owner_user_id == int(owner_user_id),
            )
            .first()
        )
        if asset is None:
            raise ValueError(f"SQL asset {asset_id} was not found")
        return asset

    def _get_owned_ask_run(self, *, ask_run_id: int, owner_user_id: int) -> VannaAskRun:
        ask_run = (
            self.db.query(VannaAskRun)
            .filter(VannaAskRun.id == int(ask_run_id))
            .first()
        )
        if ask_run is None:
            raise ValueError(f"Ask run {ask_run_id} was not found")
        kb = self.kb_service.get_kb(
            kb_id=int(ask_run.kb_id), owner_user_id=int(owner_user_id)
        )
        del kb
        return ask_run

    def _get_owned_training_entry(
        self, *, entry_id: int, owner_user_id: int
    ) -> VannaTrainingEntry:
        entry = (
            self.db.query(VannaTrainingEntry)
            .filter(VannaTrainingEntry.id == int(entry_id))
            .first()
        )
        if entry is None:
            raise ValueError(f"Training entry {entry_id} was not found")
        kb = self.kb_service.get_kb(
            kb_id=int(entry.kb_id), owner_user_id=int(owner_user_id)
        )
        del kb
        return entry

    def create_asset(
        self,
        *,
        datasource_id: int,
        owner_user_id: int,
        owner_user_name: str | None,
        kb_id: int | None,
        asset_code: str,
        name: str,
        description: str | None,
        intent_summary: str | None,
        asset_kind: str,
        match_keywords: list[str],
        match_examples: list[str],
        origin_ask_run_id: int | None = None,
        origin_training_entry_id: int | None = None,
    ) -> VannaSqlAsset:
        kb = self._resolve_kb(
            datasource_id=int(datasource_id),
            owner_user_id=int(owner_user_id),
            owner_user_name=owner_user_name,
            kb_id=kb_id,
        )
        normalized_code = asset_code.strip()
        if not normalized_code:
            raise ValueError("SQL asset code cannot be empty")
        if not name.strip():
            raise ValueError("SQL asset name cannot be empty")
        existing = (
            self.db.query(VannaSqlAsset)
            .filter(VannaSqlAsset.asset_code == normalized_code)
            .first()
        )
        if existing is not None:
            raise ValueError(f"SQL asset code already exists: {normalized_code}")

        asset = VannaSqlAsset(
            kb_id=int(kb.id),
            datasource_id=int(kb.datasource_id),
            asset_code=normalized_code,
            name=name.strip(),
            description=description,
            intent_summary=intent_summary,
            asset_kind=asset_kind,
            status=VannaSqlAssetStatus.DRAFT.value,
            system_short=kb.system_short,
            env=kb.env,
            match_keywords_json=list(match_keywords or []),
            match_examples_json=list(match_examples or []),
            owner_user_id=int(owner_user_id),
            owner_user_name=owner_user_name,
            origin_ask_run_id=origin_ask_run_id,
            origin_training_entry_id=origin_training_entry_id,
        )
        self.db.add(asset)
        self.db.commit()
        self.db.refresh(asset)
        return asset

    def list_assets(
        self,
        *,
        owner_user_id: int,
        datasource_id: int | None = None,
        kb_id: int | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> list[VannaSqlAsset]:
        query = self.db.query(VannaSqlAsset).filter(
            VannaSqlAsset.owner_user_id == int(owner_user_id)
        )
        if datasource_id is not None:
            query = query.filter(VannaSqlAsset.datasource_id == int(datasource_id))
        if kb_id is not None:
            query = query.filter(VannaSqlAsset.kb_id == int(kb_id))
        if status:
            query = query.filter(VannaSqlAsset.status == status)
        if keyword:
            like_value = f"%{keyword.strip()}%"
            query = query.filter(
                (VannaSqlAsset.asset_code.ilike(like_value))
                | (VannaSqlAsset.name.ilike(like_value))
            )
        return query.order_by(VannaSqlAsset.updated_at.desc(), VannaSqlAsset.id.desc()).all()

    def get_asset(self, *, asset_id: int, owner_user_id: int) -> VannaSqlAsset:
        return self._get_owned_asset(asset_id=int(asset_id), owner_user_id=int(owner_user_id))

    def list_versions(
        self, *, asset_id: int, owner_user_id: int
    ) -> list[VannaSqlAssetVersion]:
        asset = self._get_owned_asset(
            asset_id=int(asset_id), owner_user_id=int(owner_user_id)
        )
        return (
            self.db.query(VannaSqlAssetVersion)
            .filter(VannaSqlAssetVersion.asset_id == int(asset.id))
            .order_by(
                VannaSqlAssetVersion.version_no.desc(),
                VannaSqlAssetVersion.id.desc(),
            )
            .all()
        )

    def create_version(
        self,
        *,
        asset_id: int,
        owner_user_id: int,
        created_by: str | None,
        template_sql: str,
        parameter_schema_json: list[dict],
        render_config_json: dict,
        statement_kind: str,
        tables_read_json: list[str],
        columns_read_json: list[str],
        output_fields_json: list[str],
        version_label: str | None,
    ) -> VannaSqlAssetVersion:
        asset = self._get_owned_asset(
            asset_id=int(asset_id), owner_user_id=int(owner_user_id)
        )
        if statement_kind.upper() != "SELECT":
            raise ValueError("Only SELECT statement_kind is supported in phase 1")
        normalized_sql = template_sql.strip()
        if not normalized_sql:
            raise ValueError("template_sql cannot be empty")
        max_version_no = (
            self.db.query(VannaSqlAssetVersion.version_no)
            .filter(VannaSqlAssetVersion.asset_id == int(asset.id))
            .order_by(VannaSqlAssetVersion.version_no.desc())
            .first()
        )
        next_version_no = (int(max_version_no[0]) if max_version_no else 0) + 1
        version = VannaSqlAssetVersion(
            asset_id=int(asset.id),
            version_no=next_version_no,
            version_label=version_label,
            template_sql=normalized_sql,
            parameter_schema_json=list(parameter_schema_json or []),
            render_config_json=dict(render_config_json or {}),
            statement_kind="SELECT",
            tables_read_json=list(tables_read_json or []),
            columns_read_json=list(columns_read_json or []),
            output_fields_json=list(output_fields_json or []),
            verification_result_json={},
            quality_status=VannaSqlAssetQualityStatus.UNVERIFIED.value,
            is_published=False,
            created_by=created_by,
        )
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        return version

    def publish_version(
        self,
        *,
        asset_id: int,
        version_id: int,
        owner_user_id: int,
    ) -> VannaSqlAssetVersion:
        asset = self._get_owned_asset(
            asset_id=int(asset_id), owner_user_id=int(owner_user_id)
        )
        version = (
            self.db.query(VannaSqlAssetVersion)
            .filter(
                VannaSqlAssetVersion.id == int(version_id),
                VannaSqlAssetVersion.asset_id == int(asset.id),
            )
            .first()
        )
        if version is None:
            raise ValueError(f"SQL asset version {version_id} was not found")

        (
            self.db.query(VannaSqlAssetVersion)
            .filter(VannaSqlAssetVersion.asset_id == int(asset.id))
            .update({"is_published": False, "published_at": None})
        )
        version.is_published = True
        from datetime import UTC, datetime

        version.published_at = datetime.now(UTC).replace(tzinfo=None)
        asset.current_version_id = int(version.id)
        asset.status = VannaSqlAssetStatus.PUBLISHED.value
        self.db.commit()
        self.db.refresh(version)
        self.db.refresh(asset)
        return version

    def promote_ask_run(
        self,
        *,
        ask_run_id: int,
        owner_user_id: int,
        owner_user_name: str | None,
        asset_code: str,
        name: str,
        description: str | None,
        intent_summary: str | None,
        asset_kind: str,
        match_keywords: list[str],
        match_examples: list[str],
        parameter_schema_json: list[dict],
        render_config_json: dict,
        version_label: str | None,
    ) -> tuple[VannaSqlAsset, VannaSqlAssetVersion]:
        ask_run = self._get_owned_ask_run(
            ask_run_id=int(ask_run_id), owner_user_id=int(owner_user_id)
        )
        if not (ask_run.generated_sql or "").strip():
            raise ValueError("Ask run has no generated SQL to promote")

        asset = self.create_asset(
            datasource_id=int(ask_run.datasource_id),
            owner_user_id=int(owner_user_id),
            owner_user_name=owner_user_name,
            kb_id=int(ask_run.kb_id),
            asset_code=asset_code,
            name=name,
            description=description,
            intent_summary=intent_summary,
            asset_kind=asset_kind,
            match_keywords=match_keywords,
            match_examples=match_examples,
            origin_ask_run_id=int(ask_run.id),
        )
        version = self.create_version(
            asset_id=int(asset.id),
            owner_user_id=int(owner_user_id),
            created_by=owner_user_name,
            template_sql=str(ask_run.generated_sql),
            parameter_schema_json=parameter_schema_json,
            render_config_json=render_config_json,
            statement_kind="SELECT",
            tables_read_json=[],
            columns_read_json=[],
            output_fields_json=[],
            version_label=version_label,
        )
        return asset, version

    def promote_training_entry(
        self,
        *,
        entry_id: int,
        owner_user_id: int,
        owner_user_name: str | None,
        asset_code: str,
        name: str,
        description: str | None,
        intent_summary: str | None,
        asset_kind: str,
        match_keywords: list[str],
        match_examples: list[str],
        parameter_schema_json: list[dict],
        render_config_json: dict,
        version_label: str | None,
    ) -> tuple[VannaSqlAsset, VannaSqlAssetVersion]:
        entry = self._get_owned_training_entry(
            entry_id=int(entry_id), owner_user_id=int(owner_user_id)
        )
        if entry.entry_type != "question_sql":
            raise ValueError("Only question_sql entries can be promoted to SQL assets")
        if not (entry.sql_text or "").strip():
            raise ValueError("Training entry has no SQL text to promote")

        asset = self.create_asset(
            datasource_id=int(entry.datasource_id),
            owner_user_id=int(owner_user_id),
            owner_user_name=owner_user_name,
            kb_id=int(entry.kb_id),
            asset_code=asset_code,
            name=name,
            description=description,
            intent_summary=intent_summary,
            asset_kind=asset_kind,
            match_keywords=match_keywords,
            match_examples=match_examples,
            origin_training_entry_id=int(entry.id),
        )
        version = self.create_version(
            asset_id=int(asset.id),
            owner_user_id=int(owner_user_id),
            created_by=owner_user_name,
            template_sql=str(entry.sql_text),
            parameter_schema_json=parameter_schema_json,
            render_config_json=render_config_json,
            statement_kind=(entry.statement_kind or "SELECT"),
            tables_read_json=list(entry.tables_read_json or []),
            columns_read_json=list(entry.columns_read_json or []),
            output_fields_json=list(entry.output_fields_json or []),
            version_label=version_label,
        )
        return asset, version
