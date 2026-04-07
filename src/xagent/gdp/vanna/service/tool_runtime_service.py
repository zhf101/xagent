"""给工具层使用的 SQL 运行时门面。

这个文件的目的，是把底层多个 service 拼成“工具更容易消费”的统一入口。

对于工具层来说，它并不想关心这些内部细节：

- 先走 QueryService 还是 AskService
- SQL 资产参数如何推理
- 最终执行用哪个 execution service
- 任务确认目标和显式传入目标谁优先

因此这里提供一个比较薄、但非常关键的 runtime facade：

- `query_asset()` 给工具层一个统一的查询入口
- `execute_asset()` 给工具层一个统一的执行入口

工具层只管传问题、asset 标识和显式参数，剩下的编排都在这里完成。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from .ask_service import AskService
from .contracts import QueryResult
from .query_service import QueryService
from .sql_assets import (
    SqlAssetExecutionService,
    SqlAssetInferenceService,
    SqlAssetService,
)

logger = logging.getLogger(__name__)


class VannaToolRuntimeService:
    """供工具适配层调用的薄门面。

    “薄”并不代表不重要。它真正的价值在于：

    - 把多个 service 的组合关系固定下来
    - 把任务级目标确认逻辑统一收口
    - 把最终返回值整理成工具容易理解的字典结构
    """

    def __init__(
        self,
        db: Any,
        *,
        owner_user_id: int,
        owner_user_name: str | None,
        task_id: int | None = None,
        llm: Any | None = None,
    ) -> None:
        self.db = db
        self.owner_user_id = int(owner_user_id)
        self.owner_user_name = owner_user_name
        self.task_id = task_id

        # 如果任务上下文里已经给定了 LLM，就优先让 Query/Ask/Inference 复用它，
        # 避免同一轮工具调用里混入别的模型配置。
        task_llm_resolver = (lambda _owner_user_id: llm) if llm is not None else None
        self.query_service = QueryService(
            db,
            ask_service=(
                AskService(db, llm_resolver=task_llm_resolver)
                if task_llm_resolver is not None
                else None
            ),
            inference_service=(
                SqlAssetInferenceService(llm_resolver=task_llm_resolver)
                if task_llm_resolver is not None
                else None
            ),
        )
        self.asset_service = SqlAssetService(db)
        self.execution_service = SqlAssetExecutionService(db)

    async def query_asset(
        self,
        *,
        question: str,
        datasource_id: int | None = None,
        kb_id: int | None = None,
        explicit_params: dict[str, Any] | None = None,
        confirmed_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """查询最适合当前问题的 SQL 资产。

        这里返回的不只是“命中了哪个 asset”，还会带上：

        - ask/query 的路由结果
        - 资产和版本详情
        - 参数绑定预览
        - 可能的 ask fallback 结果
        """
        datasource_id, kb_id = self._resolve_target_ids(
            datasource_id=datasource_id,
            kb_id=kb_id,
            confirmed_target=confirmed_target,
        )
        # 对工具运行时来说，没有确认 SQL 目标就不应该继续走下去。
        if datasource_id is None:
            raise ValueError("当前任务还没有确认 SQL 目标，无法查询 SQL 资产")

        result = await self.query_service.query(
            datasource_id=int(datasource_id),
            owner_user_id=self.owner_user_id,
            create_user_name=self.owner_user_name,
            question=question,
            kb_id=kb_id,
            task_id=self.task_id,
            explicit_params=dict(explicit_params or {}),
            context={},
            auto_run=False,
            auto_infer=True,
        )

        asset = None
        version = None
        if result.asset_id is not None:
            asset = self.asset_service.get_asset(
                asset_id=int(result.asset_id),
                owner_user_id=self.owner_user_id,
            )
            version = self.asset_service.get_effective_version(
                asset_id=int(asset.id),
                owner_user_id=self.owner_user_id,
                version_id=(
                    int(result.asset_version_id)
                    if result.asset_version_id is not None
                    else None
                ),
            )
        return self._serialize_query_result(result, asset=asset, version=version)

    async def execute_asset(
        self,
        *,
        question: str,
        asset_id: int | None = None,
        asset_code: str | None = None,
        datasource_id: int | None = None,
        kb_id: int | None = None,
        version_id: int | None = None,
        explicit_params: dict[str, Any] | None = None,
        confirmed_target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行一个确定的 SQL 资产。

        这一步比 `query_asset()` 更“后置”，因为它假设模型已经知道要执行谁。
        典型调用顺序是：

        1. 先 `query_asset`
        2. 看清候选和参数
        3. 再 `execute_asset`
        """
        if asset_id is None and not (asset_code or "").strip():
            raise ValueError("asset_id 与 asset_code 至少提供一个")

        datasource_id, kb_id = self._resolve_target_ids(
            datasource_id=datasource_id,
            kb_id=kb_id,
            confirmed_target=confirmed_target,
        )

        # 先把 asset / version 解析清楚，再做参数推理和执行。
        if asset_id is not None:
            asset = self.asset_service.get_asset(
                asset_id=int(asset_id),
                owner_user_id=self.owner_user_id,
            )
        else:
            asset = self.asset_service.get_asset_by_code(
                asset_code=str(asset_code),
                owner_user_id=self.owner_user_id,
            )
        version = self.asset_service.get_effective_version(
            asset_id=int(asset.id),
            owner_user_id=self.owner_user_id,
            version_id=int(version_id) if version_id is not None else None,
        )

        normalized_context: dict[str, Any] = {}
        # 这里复用 SQL 资产推理能力，先根据自然语言问题推一个 bindings 初稿，
        # 再与显式参数合并后进入执行阶段。
        inference = await self.query_service.inference_service.infer_bindings(
            asset=asset,
            version=version,
            owner_user_id=self.owner_user_id,
            question=question,
            context=normalized_context,
        )

        run = await self.execution_service.execute(
            asset=asset,
            version=version,
            datasource_id=(
                int(datasource_id)
                if datasource_id is not None
                else int(asset.datasource_id)
            ),
            kb_id=int(kb_id) if kb_id is not None else int(asset.kb_id),
            owner_user_id=self.owner_user_id,
            owner_user_name=self.owner_user_name,
            question=question,
            explicit_params=dict(explicit_params or {}),
            context=normalized_context,
            inferred_params=dict((inference or {}).get("bindings") or {}),
            inference_assumptions=list((inference or {}).get("assumptions") or []),
            task_id=self.task_id,
        )

        binding_plan = dict(run.binding_plan_json or {})
        result = QueryResult(
            mode="asset",
            route="asset_execute",
            execution_status=str(run.execution_status),
            asset_id=int(asset.id),
            asset_version_id=int(version.id),
            asset_run_id=int(run.id),
            asset_code=str(asset.asset_code),
            compiled_sql=str(run.compiled_sql),
            bound_params=dict(run.bound_params_json or {}),
            assumptions=list(binding_plan.get("assumptions") or []),
            execution_result=dict(run.execution_result_json or {}),
            llm_inference=inference,
        )
        return self._serialize_query_result(result, asset=asset, version=version)

    def _resolve_target_ids(
        self,
        *,
        datasource_id: int | None,
        kb_id: int | None,
        confirmed_target: dict[str, Any] | None,
    ) -> tuple[int | None, int | None]:
        """统一处理工具入参目标与任务确认目标的优先级。

        规则非常明确：

        - 如果任务已经确认过 SQL 目标，优先使用任务目标
        - 工具显式传入的 datasource_id / kb_id 只在任务未确认时生效

        这样做是为了保证同一任务内的 SQL 行为稳定一致。
        """
        resolved_target = confirmed_target or {}
        resolved_datasource_id = resolved_target.get("datasource_id")
        resolved_kb_id = resolved_target.get("kb_id")

        if resolved_datasource_id is not None:
            if (
                datasource_id is not None
                and int(datasource_id) != int(resolved_datasource_id)
            ):
                logger.info(
                    "Ignoring tool-provided datasource_id=%s for task %s; using confirmed datasource_id=%s",
                    datasource_id,
                    self.task_id,
                    resolved_datasource_id,
                )
            datasource_id = int(resolved_datasource_id)

        if resolved_kb_id is not None:
            if kb_id is not None and int(kb_id) != int(resolved_kb_id):
                logger.info(
                    "Ignoring tool-provided kb_id=%s for task %s; using confirmed kb_id=%s",
                    kb_id,
                    self.task_id,
                    resolved_kb_id,
                )
            kb_id = int(resolved_kb_id)

        return datasource_id, kb_id

    def _serialize_query_result(
        self,
        result: QueryResult,
        *,
        asset: Any | None = None,
        version: Any | None = None,
    ) -> dict[str, Any]:
        """把 dataclass 结果和 ORM 对象统一折叠成工具响应字典。"""
        payload = asdict(result)
        if asset is not None:
            payload["asset"] = asset.to_dict()
        if version is not None:
            payload["version"] = version.to_dict()
        return payload

