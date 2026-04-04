"""GDP HTTP 资产应用服务。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ....web.models.gdp_http_resource import GdpHttpResource
from .http_schema_bridge import build_schema_and_routes_from_tree
from .http_runtime_service import (
    HttpInvoker,
    HttpRequestAssembler,
    HttpRuntimeDefinitionAssembler,
)
from ..http_asset_protocol import (
    GdpHttpAssetAssembleRequest,
    GdpHttpAssetAssembleResponse,
    GdpHttpAssetNormalizeRequest,
    GdpHttpAssetNormalizeResponse,
    GdpHttpAssetStatus,
    GdpHttpAssetUpsertRequest,
)
from ..http_asset_validator import GdpHttpAssetValidationError, GdpHttpAssetValidator


class GdpHttpResourceService:
    """GDP HTTP 资产 CRUD 服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.validator = GdpHttpAssetValidator()
        # 这里让后台预览拼装复用运行时组件，确保 assemble 和 execute 看到的是同一套规则。
        self.definition_assembler = HttpRuntimeDefinitionAssembler()
        self.request_assembler = HttpRequestAssembler()
        self.invoker = HttpInvoker()

    def list_assets(self, user_id: int) -> list[GdpHttpResource]:
        """列出当前用户可见且未删除的资产。"""
        del user_id
        return (
            self.db.query(GdpHttpResource)
            .filter(
                GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
            )
            .order_by(GdpHttpResource.updated_at.desc(), GdpHttpResource.id.desc())
            .all()
        )

    def get_asset(self, asset_id: int, user_id: int) -> GdpHttpResource | None:
        """读取单个资产详情。"""
        del user_id
        return (
            self.db.query(GdpHttpResource)
            .filter(
                GdpHttpResource.id == int(asset_id),
                GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
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

    def assemble_request(
        self,
        *,
        request: GdpHttpAssetAssembleRequest,
    ) -> GdpHttpAssetAssembleResponse:
        """根据资产配置和提供的 Mock 参数，组装真实的请求内容（预览用）。

        这里显式复用 runtime definition + request assembler：
        - 避免预览拼装和真实执行各走一套逻辑
        - 让 `url_mode=tag`、query/body/path/header 路由规则天然保持一致
        """
        self.validator.validate(request.payload)
        definition = self.definition_assembler.assemble_from_upsert_payload(
            request.payload
        )
        request_snapshot = self.request_assembler.build(
            definition=definition,
            arguments=dict(request.mock_args or {}),
        )
        preview_headers = self.invoker.preview_headers(
            definition=definition,
            headers=request_snapshot.headers,
        )
        body_content = self._serialize_preview_body(request_snapshot)

        return GdpHttpAssetAssembleResponse(
            url=request_snapshot.url,
            method=request_snapshot.method,
            headers={str(k): str(v) for k, v in preview_headers.items()},
            body=body_content,
        )

    def normalize_payload(
        self,
        *,
        request: GdpHttpAssetNormalizeRequest,
    ) -> GdpHttpAssetNormalizeResponse:
        """把前端 draft payload 归一化为最终落库/预览使用的 payload。

        visual tree 的 schema/routes 产物由后端统一生成，并立即复用同一套
        validator，避免前端保存前推导与后端运行时规则分叉。
        """
        payload = request.payload.model_copy(deep=True)

        if request.input_tree is not None:
            input_schema, args_position = build_schema_and_routes_from_tree(
                request.input_tree
            )
            payload.tool_contract.input_schema_json = input_schema
            payload.execution_profile.args_position_json = args_position

        if request.output_tree is not None:
            output_schema, _ = build_schema_and_routes_from_tree(request.output_tree)
            payload.tool_contract.output_schema_json = output_schema

        self.validator.validate(payload)
        return GdpHttpAssetNormalizeResponse(payload=payload)

    def _serialize_preview_body(self, request_snapshot: Any) -> str | None:
        """把运行时请求快照折叠成 assemble API 的响应形态。

        assemble 接口当前历史协议只返回一个 `body: str | null`，
        因此这里需要把 JSON body 重新序列化成字符串。
        """
        if getattr(request_snapshot, "text_body", None) is not None:
            return str(request_snapshot.text_body)
        if getattr(request_snapshot, "json_body", None) is not None:
            return json.dumps(request_snapshot.json_body, ensure_ascii=False)
        return None

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
