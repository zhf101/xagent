"""GDP HTTP 资产应用服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....web.models.gdp_http_resource import GdpHttpResource
from ..http_asset_protocol import GdpHttpAssetStatus, GdpHttpAssetUpsertRequest
from ..http_asset_validator import GdpHttpAssetValidationError, GdpHttpAssetValidator


class GdpHttpResourceService:
    """GDP HTTP 资产 CRUD 服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.validator = GdpHttpAssetValidator()

    def list_assets(self, user_id: int) -> list[GdpHttpResource]:
        """列出当前用户可见且未删除的资产。"""
        return (
            self.db.query(GdpHttpResource)
            .filter(
                GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
                or_(
                    GdpHttpResource.create_user_id == int(user_id),
                    GdpHttpResource.visibility.in_(["shared", "global"]),
                ),
            )
            .order_by(GdpHttpResource.updated_at.desc(), GdpHttpResource.id.desc())
            .all()
        )

    def get_asset(self, asset_id: int, user_id: int) -> GdpHttpResource | None:
        """读取单个资产详情。"""
        return (
            self.db.query(GdpHttpResource)
            .filter(
                GdpHttpResource.id == int(asset_id),
                GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
                or_(
                    GdpHttpResource.create_user_id == int(user_id),
                    GdpHttpResource.visibility.in_(["shared", "global"]),
                ),
            )
            .first()
        )

    def create_asset(
        self,
        *,
        user_id: int,
        user_name: str | None,
        payload: GdpHttpAssetUpsertRequest,
    ) -> GdpHttpResource:
        """创建资产并在落库前完成协议校验。"""
        self.validator.validate(payload)

        resource = GdpHttpResource(
            resource_key=payload.resource.resource_key,
            system_short=payload.resource.system_short,
            create_user_id=int(user_id),
            create_user_name=(user_name or "").strip() or None,
            visibility=payload.resource.visibility,
            status=int(GdpHttpAssetStatus.ACTIVE),
            summary=payload.resource.summary,
            tags_json=payload.resource.tags_json,
            tool_name=payload.tool_contract.tool_name,
            tool_description=payload.tool_contract.tool_description,
            input_schema_json=payload.tool_contract.input_schema_json,
            output_schema_json=payload.tool_contract.output_schema_json,
            annotations_json=payload.tool_contract.annotations_json,
            method=payload.execution_profile.method,
            url_mode=payload.execution_profile.url_mode,
            direct_url=payload.execution_profile.direct_url,
            sys_label=payload.execution_profile.sys_label,
            url_suffix=payload.execution_profile.url_suffix,
            args_position_json=payload.execution_profile.args_position_json,
            request_template_json=payload.execution_profile.request_template_json,
            response_template_json=payload.execution_profile.response_template_json,
            error_response_template=payload.execution_profile.error_response_template,
            auth_json=payload.execution_profile.auth_json,
            headers_json=payload.execution_profile.headers_json,
            timeout_seconds=payload.execution_profile.timeout_seconds,
        )
        self.db.add(resource)
        self._commit_with_unique_guard()
        self.db.refresh(resource)
        return resource

    def update_asset(
        self,
        *,
        asset_id: int,
        user_id: int,
        payload: GdpHttpAssetUpsertRequest,
    ) -> GdpHttpResource:
        """仅允许创建人更新，且已删除资产不可修改。"""
        self.validator.validate(payload)
        resource = self._get_mutable_asset(asset_id=asset_id, user_id=user_id)

        resource.resource_key = payload.resource.resource_key
        resource.system_short = payload.resource.system_short
        resource.visibility = payload.resource.visibility
        resource.summary = payload.resource.summary
        resource.tags_json = payload.resource.tags_json

        resource.tool_name = payload.tool_contract.tool_name
        resource.tool_description = payload.tool_contract.tool_description
        resource.input_schema_json = payload.tool_contract.input_schema_json
        resource.output_schema_json = payload.tool_contract.output_schema_json
        resource.annotations_json = payload.tool_contract.annotations_json

        resource.method = payload.execution_profile.method
        resource.url_mode = payload.execution_profile.url_mode
        resource.direct_url = payload.execution_profile.direct_url
        resource.sys_label = payload.execution_profile.sys_label
        resource.url_suffix = payload.execution_profile.url_suffix
        resource.args_position_json = payload.execution_profile.args_position_json
        resource.request_template_json = payload.execution_profile.request_template_json
        resource.response_template_json = payload.execution_profile.response_template_json
        resource.error_response_template = payload.execution_profile.error_response_template
        resource.auth_json = payload.execution_profile.auth_json
        resource.headers_json = payload.execution_profile.headers_json
        resource.timeout_seconds = payload.execution_profile.timeout_seconds

        self._commit_with_unique_guard()
        self.db.refresh(resource)
        return resource

    def delete_asset(self, *, asset_id: int, user_id: int) -> GdpHttpResource:
        """软删除资产，把状态改成 deleted。"""
        resource = self._get_mutable_asset(asset_id=asset_id, user_id=user_id)
        resource.status = int(GdpHttpAssetStatus.DELETED)
        self.db.commit()
        self.db.refresh(resource)
        return resource

    def _get_mutable_asset(self, *, asset_id: int, user_id: int) -> GdpHttpResource:
        """查询允许当前用户修改的资产。"""
        resource = (
            self.db.query(GdpHttpResource)
            .filter(
                GdpHttpResource.id == int(asset_id),
                GdpHttpResource.create_user_id == int(user_id),
            )
            .first()
        )
        if resource is None:
            raise ValueError("未找到或无权修改该资产")
        if int(resource.status) == int(GdpHttpAssetStatus.DELETED):
            raise ValueError("已删除资产不允许修改")
        return resource

    def _commit_with_unique_guard(self) -> None:
        """统一处理唯一键冲突，避免把数据库异常直接透给 API 层。"""
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise GdpHttpAssetValidationError("resource_key 已存在") from exc
