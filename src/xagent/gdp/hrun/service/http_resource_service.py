"""HTTP 资产的应用服务层。

这个文件可以理解为“后台配置 HTTP 资产”对应的核心服务。

它负责三类事情：

1. CRUD
   管理 HTTP 资产的增删改查、可见性和软删除
2. 注册期校验
   在资产落库前检查 resource_key、参数路径、模板结构是否合法
3. 预览期复用运行时
   `assemble_request` / `normalize_payload` 虽然是后台接口，
   但会尽量复用真正运行时的拼装组件，避免预览和执行走成两套逻辑

和它配套的另一个核心文件是 `http_runtime_service.py`：

- `http_resource_service.py` 负责“把资产配对、存好”
- `http_runtime_service.py` 负责“把资产真的跑起来”
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from xagent.gdp.hrun.model.http_resource import GdpHttpResource
from xagent.gdp.hrun.adapter.http_schema_bridge import build_schema_and_routes_from_tree
from .http_runtime_service import (
    HttpInvoker,
    HttpRequestAssembler,
    HttpRuntimeDefinitionAssembler,
)
from xagent.gdp.hrun.adapter.http_asset_protocol import (
    GdpHttpAssetAssembleRequest,
    GdpHttpAssetAssembleResponse,
    GdpHttpAssetNormalizeRequest,
    GdpHttpAssetNormalizeResponse,
    GdpHttpAssetStatus,
    GdpHttpAssetUpsertRequest,
)
from xagent.gdp.hrun.util.http_asset_validator import GdpHttpAssetValidationError, GdpHttpAssetValidator


class GdpHttpResourceService:
    """HTTP 资产 CRUD 与注册期辅助服务。"""

    def __init__(self, db: Session):
        self.db = db
        self.validator = GdpHttpAssetValidator()
        # 这里让后台预览拼装复用运行时组件，确保 assemble 和 execute 看到的是同一套规则。
        # 对新人来说，这一点很重要：不要让“预览能过，真实执行却跑不通”。
        self.definition_assembler = HttpRuntimeDefinitionAssembler()
        self.request_assembler = HttpRequestAssembler()
        self.invoker = HttpInvoker()

    def list_assets(self, user_id: int) -> list[GdpHttpResource]:
        """列出当前用户可见且未删除的资产。"""
        return (
            self.db.query(GdpHttpResource)
            .filter(
                GdpHttpResource.status != int(GdpHttpAssetStatus.DELETED),
            )
            .filter(
                or_(
                    GdpHttpResource.create_user_id == int(user_id),
                    GdpHttpResource.visibility.in_(["shared", "global"]),
                )
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
        # 所有新建资产都必须先过注册期校验，避免把坏配置写入数据库。
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
        # 更新和创建共用同一套 validator，保证规则完全一致。
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
        # 预览前也要先校验 payload，防止前端拿一份半成品配置就来预览。
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
        # 这里先复制一份 payload，而不是原地修改请求对象，避免副作用污染上游。
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
        """查询允许当前用户修改的资产。

        这里统一封装“谁能改”的规则，避免 update/delete 各写一遍权限判断。
        """
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
        """统一处理唯一键冲突，避免把数据库异常直接透给 API 层。

        新人经常会在 API 层直接 try/except 数据库异常，但这种处理容易分散。
        这里集中做掉后，API 层就只需要关注 HTTP 语义。
        """
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise GdpHttpAssetValidationError("resource_key 已存在") from exc

