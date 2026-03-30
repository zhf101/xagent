"""
`Resource Result Normalizer`（资源结果归一化器）模块。

这一层负责把 `Resource` 返回的原始事实，转换成 Runtime 可稳定消费的
结构化执行结论，但不会丢掉原始返回。
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..contracts.constants import (
    BUSINESS_STATUS_FAILED,
    BUSINESS_STATUS_SUCCESS,
    EXECUTION_MODE_PROBE,
    PROTOCOL_STATUS_FAILED,
    PROTOCOL_STATUS_SUCCESS,
    RUNTIME_STATUS_FAILED,
    RUNTIME_STATUS_SUCCESS,
)
from ..contracts.runtime import CompiledExecutionContract


class NormalizedExecutionOutcome(BaseModel):
    """
    `NormalizedExecutionOutcome`（归一化执行结论）。

    这里表达的是 Runtime 对资源原始返回的结构化理解结果，
    而不是对资源原始返回的替换。
    原始事实仍然必须单独保留在 `raw_result / raw_error` 中。
    """

    status: str = Field(
        default="success",
        description="Runtime 最终认定的整体状态。"
    )
    summary: str = Field(
        default="",
        description="面向上游主脑的摘要。"
    )
    error: str | None = Field(
        default=None,
        description="失败时的错误摘要。"
    )
    facts: dict[str, Any] = Field(
        default_factory=dict,
        description="transport / protocol / business 等多层执行事实。"
    )


class ResourceResultNormalizer(Protocol):
    """
    `ResourceResultNormalizer`（资源结果归一化器协议）。

    每个资源动作都可以绑定一个 normalizer，用于把原始结果归一化成 Runtime 结论。
    """

    name: str

    def normalize_result(
        self,
        raw_result: Any,
        *,
        contract: CompiledExecutionContract,
        result_contract: dict[str, Any],
    ) -> NormalizedExecutionOutcome:
        """
        处理资源成功返回的原始结果。
        """

    def normalize_exception(
        self,
        exc: Exception,
        *,
        contract: CompiledExecutionContract,
        result_contract: dict[str, Any],
    ) -> NormalizedExecutionOutcome:
        """
        处理资源执行阶段抛出的异常。
        """


class PassThroughResultNormalizer:
    """
    `PassThroughResultNormalizer`（透传归一化器）。

    适合没有额外协议/业务状态约束的资源动作。
    只要资源成功返回，就视为整体执行成功，同时保留全部原始事实。
    """

    name = "passthrough"

    def normalize_result(
        self,
        raw_result: Any,
        *,
        contract: CompiledExecutionContract,
        result_contract: dict[str, Any],
    ) -> NormalizedExecutionOutcome:
        adapter_label = str(contract.metadata.get("adapter_kind", "resource")).upper()
        mode_label = "探测执行" if contract.mode == EXECUTION_MODE_PROBE else "正式执行"
        return NormalizedExecutionOutcome(
            status=RUNTIME_STATUS_SUCCESS,
            summary=f"{adapter_label} {mode_label}成功",
            facts={
                "normalizer": self.name,
                "transport_status": "success",
                "protocol_status": "unknown",
                "business_status": "unknown",
            },
        )

    def normalize_exception(
        self,
        exc: Exception,
        *,
        contract: CompiledExecutionContract,
        result_contract: dict[str, Any],
    ) -> NormalizedExecutionOutcome:
        adapter_label = str(contract.metadata.get("adapter_kind", "resource")).upper()
        mode_label = "探测执行" if contract.mode == EXECUTION_MODE_PROBE else "正式执行"
        return NormalizedExecutionOutcome(
            status=RUNTIME_STATUS_FAILED,
            summary=f"{adapter_label} {mode_label}失败",
            error=str(exc),
            facts={
                "normalizer": self.name,
                "transport_status": "failed",
                "protocol_status": "unknown",
                "business_status": "unknown",
            },
        )


class StructuredHttpResultNormalizer:
    """
    `StructuredHttpResultNormalizer`（结构化 HTTP 结果归一化器）。

    这类资源动作会把“传输成功”“HTTP 协议成功”“业务成功”三层事实拆开记录。
    注意：
    - `HTTP 200` 只能说明协议层成功，不能自动推出业务成功。
    - 若资源动作声明了业务成功字段，则以业务字段作为最终是否达成目标的依据。
    - 但“业务是否达成”仍然只是事实归一化，不应被这里偷换成下一步业务动作决策。
      Runtime 只负责把事实拆开给上游看，不负责替 Agent 下结论。
    """

    name = "http_structured"

    def normalize_result(
        self,
        raw_result: Any,
        *,
        contract: CompiledExecutionContract,
        result_contract: dict[str, Any],
    ) -> NormalizedExecutionOutcome:
        payload = self._coerce_mapping(raw_result)
        http_status = self._extract_http_status(payload, result_contract)
        protocol_status = self._resolve_protocol_status(http_status, result_contract)
        business_status = self._resolve_business_status(payload, result_contract)
        error = self._extract_error(payload, result_contract)
        overall_status = self._resolve_overall_status(protocol_status, business_status)

        mode_label = "探测执行" if contract.mode == EXECUTION_MODE_PROBE else "正式执行"
        summary = self._build_summary(
            mode_label=mode_label,
            overall_status=overall_status,
            protocol_status=protocol_status,
            business_status=business_status,
            http_status=http_status,
            error=error,
        )

        return NormalizedExecutionOutcome(
            status=overall_status,
            summary=summary,
            error=error if protocol_status == PROTOCOL_STATUS_FAILED else None,
            facts={
                "normalizer": self.name,
                "transport_status": "success",
                "protocol_status": protocol_status,
                "business_status": business_status,
                "http_status": http_status,
                "business_error": error,
                "result_contract": dict(result_contract),
            },
        )

    def normalize_exception(
        self,
        exc: Exception,
        *,
        contract: CompiledExecutionContract,
        result_contract: dict[str, Any],
    ) -> NormalizedExecutionOutcome:
        mode_label = "探测执行" if contract.mode == EXECUTION_MODE_PROBE else "正式执行"
        return NormalizedExecutionOutcome(
            status=RUNTIME_STATUS_FAILED,
            summary=f"HTTP {mode_label}失败",
            error=str(exc),
            facts={
                "normalizer": self.name,
                "transport_status": "failed",
                "protocol_status": "unknown",
                "business_status": "unknown",
                "http_status": None,
                "result_contract": dict(result_contract),
            },
        )

    def _coerce_mapping(self, raw_result: Any) -> dict[str, Any] | None:
        """
        把 dict / pydantic model 统一转成 mapping，便于按契约取字段。
        """

        if isinstance(raw_result, dict):
            return raw_result
        if hasattr(raw_result, "model_dump"):
            dumped = raw_result.model_dump(mode="json")
            if isinstance(dumped, dict):
                return dumped
        return None

    def _extract_http_status(
        self,
        payload: dict[str, Any] | None,
        result_contract: dict[str, Any],
    ) -> int | None:
        """
        从原始返回中读取 HTTP 状态码。
        """

        if payload is None:
            return None

        field_name = str(result_contract.get("http_status_field", "")).strip()
        candidate_fields = [field_name] if field_name else []
        candidate_fields.extend(["http_status", "status_code", "status"])

        for field in candidate_fields:
            if not field or field not in payload:
                continue
            value = payload.get(field)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return None

    def _resolve_protocol_status(
        self,
        http_status: int | None,
        result_contract: dict[str, Any],
    ) -> str:
        """
        判断 HTTP 协议层是否成功。
        """

        if http_status is None:
            return "unknown"

        configured_statuses = result_contract.get("success_http_statuses")
        if isinstance(configured_statuses, list) and configured_statuses:
            return "success" if http_status in configured_statuses else "failed"

        return "success" if 200 <= http_status < 300 else "failed"

    def _resolve_business_status(
        self,
        payload: dict[str, Any] | None,
        result_contract: dict[str, Any],
    ) -> str:
        """
        判断业务层是否成功。

        若资源动作没有声明业务成功字段，则保留为 unknown，
        由上游知道这里只能确认“协议层成功”，不能确认业务目标已达成。
        """

        if payload is None:
            return "unknown"

        field_name = str(result_contract.get("business_success_field", "success")).strip()
        if not field_name or field_name not in payload:
            return "unknown"

        value = payload.get(field_name)
        if value is True:
            return "success"
        if value is False:
            return "failed"
        return "unknown"

    def _extract_error(
        self,
        payload: dict[str, Any] | None,
        result_contract: dict[str, Any],
    ) -> str | None:
        """
        尝试从原始返回里提取业务错误字段。
        """

        if payload is None:
            return None

        field_name = str(result_contract.get("business_error_field", "error")).strip()
        if field_name and field_name in payload and payload.get(field_name) not in (None, ""):
            return str(payload.get(field_name))
        return None

    def _resolve_overall_status(
        self,
        protocol_status: str,
        business_status: str,
    ) -> str:
        """
        归并出 Runtime 最终状态。

        关键边界：
        - Runtime 的整体 `failed` 只代表“技术执行链本身失败”，例如协议层失败。
        - 业务层 `failed` 只是一条业务事实，不应让 Runtime 越权替 Agent 判定任务失败。
        """

        if protocol_status == PROTOCOL_STATUS_FAILED:
            return RUNTIME_STATUS_FAILED
        return RUNTIME_STATUS_SUCCESS

    def _build_summary(
        self,
        *,
        mode_label: str,
        overall_status: str,
        protocol_status: str,
        business_status: str,
        http_status: int | None,
        error: str | None,
    ) -> str:
        """
        生成人类可读的执行摘要。
        """

        if overall_status == RUNTIME_STATUS_FAILED:
            if protocol_status == PROTOCOL_STATUS_FAILED:
                return (
                    f"HTTP {mode_label}失败："
                    f"协议层返回异常状态码 {http_status}"
                )
            return f"HTTP {mode_label}失败"

        if business_status == BUSINESS_STATUS_FAILED:
            return (
                f"HTTP {mode_label}已完成："
                f"业务结果显示失败{f'，原因：{error}' if error else ''}"
            )
        if business_status == BUSINESS_STATUS_SUCCESS:
            return f"HTTP {mode_label}成功：业务结果已确认成功"
        if protocol_status == PROTOCOL_STATUS_SUCCESS:
            return f"HTTP {mode_label}成功：已收到协议层成功响应"
        return f"HTTP {mode_label}成功"
