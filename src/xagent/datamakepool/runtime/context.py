"""Datamakepool 模板运行时上下文。"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from xagent.core.tools.core.mcp.sessions import Connection
from xagent.core.workspace import TaskWorkspace
from xagent.web.models.datamakepool_asset import DataMakepoolAsset

from .models import TemplateRecordedStepResult, TemplateRuntimeStep, TemplateStepResult

_PLACEHOLDER_RE = re.compile(
    r"\{\{\s*([^{}]+?)\s*\}\}|\$\{([^{}]+?)\}|\{([^{}]+?)\}"
)
_FULL_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:\{\{\s*([^{}]+?)\s*\}\}|\$\{([^{}]+?)\}|\{([^{}]+?)\})\s*$"
)
_DIRECT_STEP_EXPR_RE = re.compile(
    r"^steps\.[a-zA-Z_][a-zA-Z0-9_]*\.(?:output|summary|data(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)$"
)
_MISSING = object()
_SAFE_EXPR_FUNCS = {
    "coalesce",
    "default",
    "format",
    "concat",
    "join",
    "length",
    "lower",
    "upper",
    "contains",
    "to_json",
}


@dataclass
class TemplateRuntimeContext:
    """模板直跑共享运行时上下文。

    这里集中承载三类能力：
    - 入参快照与占位符渲染
    - 已完成步骤结果缓存，支持后续步骤引用
    - 资产 / MCP 连接等执行期共享依赖访问
    """

    input_params: dict[str, Any]
    db: Session | None = None
    workspace: TaskWorkspace | None = None
    mcp_configs: list[dict[str, Any]] = field(default_factory=list)
    user_id: int | None = None
    run_id: int | None = None
    _step_results: dict[str, TemplateRecordedStepResult] = field(
        default_factory=dict, init=False, repr=False
    )
    _asset_cache: dict[int, DataMakepoolAsset | None] = field(
        default_factory=dict, init=False, repr=False
    )
    _mcp_connection_map: dict[str, Connection] | None = field(
        default=None, init=False, repr=False
    )

    def set_run_id(self, run_id: int | None) -> None:
        """记录当前运行账本 ID，方便后续扩展 trace / 审批恢复。"""

        self.run_id = run_id

    def record_step_result(
        self, step: TemplateRuntimeStep, result: TemplateStepResult
    ) -> None:
        """把已完成步骤结果写入上下文，供后续步骤引用。"""

        self._step_results[step.name] = TemplateRecordedStepResult(
            step_order=step.order,
            step_name=step.name,
            executor_type=step.kind,
            output=result.output,
            summary=result.summary,
            data=self.json_safe(result.output_data),
        )

    def get_step_result(self, step_name: str) -> TemplateRecordedStepResult | None:
        """读取某个已完成步骤结果。"""

        return self._step_results.get(step_name)

    def restore_step_result(
        self,
        *,
        step_name: str,
        step_order: int,
        executor_type: str,
        output_data: dict[str, Any] | None,
    ) -> None:
        """从持久化账本恢复已完成步骤结果。

        断点续跑时不会重新执行已完成步骤，因此需要先把账本里的输出重新灌回
        runtime context，保证后续依赖步骤还能解析 `steps.xxx` 引用。
        """

        normalized = self.json_safe(output_data or {})
        self._step_results[step_name] = TemplateRecordedStepResult(
            step_order=step_order,
            step_name=step_name,
            executor_type=executor_type,
            output=str(normalized.get("output") or ""),
            summary=(
                str(normalized["summary"])
                if normalized.get("summary") not in (None, "")
                else None
            ),
            data=normalized,
        )

    def render_value(
        self,
        value: Any,
        *,
        allow_step_refs: bool,
        strict_steps: bool,
        fail_on_missing_params: bool = True,
    ) -> Any:
        """递归渲染模板值。

        约束说明：
        - 参数占位符必须在执行前被解析，否则视为缺参
        - step 引用是否允许、是否要求“已产出结果”，由调用方决定
        """

        if isinstance(value, str):
            return self._render_string(
                value,
                allow_step_refs=allow_step_refs,
                strict_steps=strict_steps,
                fail_on_missing_params=fail_on_missing_params,
            )
        if isinstance(value, dict):
            return {
                key: self.render_value(
                    item,
                    allow_step_refs=allow_step_refs,
                    strict_steps=strict_steps,
                    fail_on_missing_params=fail_on_missing_params,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self.render_value(
                    item,
                    allow_step_refs=allow_step_refs,
                    strict_steps=strict_steps,
                    fail_on_missing_params=fail_on_missing_params,
                )
                for item in value
            ]
        return value

    def contains_unresolved_placeholders(
        self, value: Any, *, allow_step_refs: bool
    ) -> bool:
        """判断值里是否还残留未允许的占位符。"""

        if isinstance(value, str):
            for match in _PLACEHOLDER_RE.finditer(value):
                expr = self._match_expr(match)
                if allow_step_refs and "steps." in expr:
                    continue
                return True
            return False
        if isinstance(value, dict):
            return any(
                self.contains_unresolved_placeholders(
                    item,
                    allow_step_refs=allow_step_refs,
                )
                for item in value.values()
            )
        if isinstance(value, list):
            return any(
                self.contains_unresolved_placeholders(
                    item,
                    allow_step_refs=allow_step_refs,
                )
                for item in value
            )
        return False

    def resolve_asset(self, asset_id: Any) -> DataMakepoolAsset | None:
        """按需加载资产并做简单缓存。"""

        normalized = self.coerce_int(asset_id)
        if normalized is None or self.db is None:
            return None
        if normalized not in self._asset_cache:
            self._asset_cache[normalized] = (
                self.db.query(DataMakepoolAsset)
                .filter(DataMakepoolAsset.id == normalized)
                .first()
            )
        return self._asset_cache[normalized]

    def get_mcp_connection(self, server_name: str) -> Connection | None:
        """把 web 层透传的 MCP 配置转换成 session 需要的 Connection。"""

        if self._mcp_connection_map is None:
            connection_map: dict[str, Connection] = {}
            for config in self.mcp_configs:
                name = str(config.get("name") or "").strip()
                transport = str(config.get("transport") or "").strip()
                if not name or not transport:
                    continue
                connection = {
                    "transport": transport,
                    **dict(config.get("config") or {}),
                }
                connection_map[name] = connection  # type: ignore[assignment]
            self._mcp_connection_map = connection_map
        return self._mcp_connection_map.get(server_name)

    def extract_step_dependencies(self, value: Any) -> list[str]:
        """从模板值里提取显式 `steps.xxx` 依赖。"""

        dependencies: list[str] = []

        def visit(node: Any) -> None:
            if isinstance(node, str):
                for match in _PLACEHOLDER_RE.finditer(node):
                    expr = self._match_expr(match)
                    if not expr.startswith("steps."):
                        continue
                    parts = expr.split(".")
                    if len(parts) >= 3:
                        dependency = parts[1].strip()
                        if dependency and dependency not in dependencies:
                            dependencies.append(dependency)
                return
            if isinstance(node, dict):
                for child in node.values():
                    visit(child)
                return
            if isinstance(node, list):
                for child in node:
                    visit(child)

        visit(value)
        return dependencies

    def evaluate_when(self, expression: str | None) -> bool:
        """计算步骤 `when` 条件。

        Phase 2 先支持足够保守的布尔语义：
        - 空值视为 True
        - 占位符渲染后支持 bool / 数值 / 字符串真假值
        """

        if expression in (None, ""):
            return True
        rendered = self.render_value(
            expression,
            allow_step_refs=True,
            strict_steps=True,
        )
        if isinstance(rendered, bool):
            return rendered
        if isinstance(rendered, (int, float)):
            return bool(rendered)
        normalized = str(rendered).strip().lower()
        if normalized in {"", "0", "false", "no", "off", "none", "null"}:
            return False
        return True

    def _render_string(
        self,
        value: str,
        *,
        allow_step_refs: bool,
        strict_steps: bool,
        fail_on_missing_params: bool,
    ) -> Any:
        full_match = _FULL_PLACEHOLDER_RE.match(value)
        if full_match:
            expr = self._match_expr(full_match)
            resolved = self._resolve_expression(
                expr,
                allow_step_refs=allow_step_refs,
                strict_steps=strict_steps,
                fail_on_missing_params=fail_on_missing_params,
            )
            if resolved is not _MISSING:
                return resolved

        def replace(match: re.Match[str]) -> str:
            expr = self._match_expr(match)
            resolved = self._resolve_expression(
                expr,
                allow_step_refs=allow_step_refs,
                strict_steps=strict_steps,
                fail_on_missing_params=fail_on_missing_params,
            )
            if resolved is _MISSING:
                return match.group(0)
            if resolved is None:
                return ""
            if isinstance(resolved, (dict, list)):
                return json.dumps(resolved, ensure_ascii=False, default=str)
            return str(resolved)

        return _PLACEHOLDER_RE.sub(replace, value)

    def _resolve_expression(
        self,
        expr: str,
        *,
        allow_step_refs: bool,
        strict_steps: bool,
        fail_on_missing_params: bool,
    ) -> Any:
        normalized_expr = expr.strip()
        if _DIRECT_STEP_EXPR_RE.fullmatch(normalized_expr):
            if not allow_step_refs:
                raise ValueError(f"step_reference_not_allowed:{normalized_expr}")
            return self._resolve_step_expression(
                normalized_expr,
                strict_steps=strict_steps,
            )

        if normalized_expr in self.input_params:
            return self.input_params.get(normalized_expr)

        try:
            return self._eval_expression(normalized_expr)
        except Exception:
            if allow_step_refs and not strict_steps and "steps." in normalized_expr:
                return _MISSING

        if fail_on_missing_params:
            raise ValueError(f"missing_required_param:{normalized_expr}")
        return _MISSING

    def _resolve_step_expression(self, expr: str, *, strict_steps: bool) -> Any:
        parts = expr.split(".")
        if len(parts) < 3 or parts[0] != "steps":
            raise ValueError(f"invalid_step_reference:{expr}")

        step_name = parts[1]
        step_result = self._step_results.get(step_name)
        if step_result is None:
            if strict_steps:
                raise ValueError(f"step_result_not_ready:{step_name}")
            return _MISSING

        target = parts[2]
        if target == "output":
            value: Any = step_result.output
        elif target == "summary":
            value = step_result.summary
        elif target == "data":
            value = step_result.data
            for segment in parts[3:]:
                if isinstance(value, dict) and segment in value:
                    value = value[segment]
                    continue
                if strict_steps:
                    raise ValueError(f"step_result_path_not_found:{expr}")
                return _MISSING
        else:
            raise ValueError(f"invalid_step_reference:{expr}")
        return value

    def _eval_expression(self, expression: str) -> Any:
        """安全求值受限表达式。

        支持能力：
        - 参数与 `steps.xxx` 结果引用
        - `and/or/not`
        - `== != > >= < <=`
        - `+`
        - 三元表达式 `a if cond else b`
        - 少量受控函数：`coalesce/default/format/concat/join/length/lower/upper/contains/to_json`
        """

        tree = ast.parse(expression, mode="eval")
        return self._eval_ast_node(tree.body)

    def _eval_ast_node(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in {"True", "False", "None"}:
                return {"True": True, "False": False, "None": None}[node.id]
            if node.id == "steps":
                return self._step_results
            if node.id in self.input_params:
                return self.input_params.get(node.id)
            raise ValueError(f"unknown_expression_name:{node.id}")
        if isinstance(node, ast.Attribute):
            base = self._eval_ast_node(node.value)
            return self._resolve_attr_or_key(base, node.attr)
        if isinstance(node, ast.Subscript):
            base = self._eval_ast_node(node.value)
            key = self._eval_ast_node(node.slice)
            return self._resolve_attr_or_key(base, key)
        if isinstance(node, ast.BoolOp):
            values = [self._eval_ast_node(item) for item in node.values]
            if isinstance(node.op, ast.And):
                result = True
                for value in values:
                    result = result and bool(value)
                    if not result:
                        break
                return result
            if isinstance(node.op, ast.Or):
                result = False
                for value in values:
                    result = result or bool(value)
                    if result:
                        break
                return result
            raise ValueError("unsupported_boolean_operator")
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_ast_node(node.operand)
            if isinstance(node.op, ast.Not):
                return not bool(operand)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            raise ValueError("unsupported_unary_operator")
        if isinstance(node, ast.BinOp):
            left = self._eval_ast_node(node.left)
            right = self._eval_ast_node(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            raise ValueError("unsupported_binary_operator")
        if isinstance(node, ast.Compare):
            left = self._eval_ast_node(node.left)
            current = left
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._eval_ast_node(comparator)
                passed = self._apply_compare(operator, current, right)
                if not passed:
                    return False
                current = right
            return True
        if isinstance(node, ast.IfExp):
            condition = self._eval_ast_node(node.test)
            return self._eval_ast_node(node.body if condition else node.orelse)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_EXPR_FUNCS:
                raise ValueError("unsupported_expression_function")
            args = [self._eval_ast_node(arg) for arg in node.args]
            kwargs = {
                kw.arg: self._eval_ast_node(kw.value)
                for kw in node.keywords
                if kw.arg is not None
            }
            return self._call_safe_function(node.func.id, args, kwargs)
        if isinstance(node, ast.List):
            return [self._eval_ast_node(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return [self._eval_ast_node(item) for item in node.elts]
        if isinstance(node, ast.Dict):
            return {
                self._eval_ast_node(key): self._eval_ast_node(value)
                for key, value in zip(node.keys, node.values)
                if key is not None
            }
        raise ValueError(f"unsupported_expression_node:{type(node).__name__}")

    @staticmethod
    def _apply_compare(operator: ast.AST, left: Any, right: Any) -> bool:
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.NotEq):
            return left != right
        if isinstance(operator, ast.Gt):
            return left > right
        if isinstance(operator, ast.GtE):
            return left >= right
        if isinstance(operator, ast.Lt):
            return left < right
        if isinstance(operator, ast.LtE):
            return left <= right
        if isinstance(operator, ast.In):
            return left in right
        if isinstance(operator, ast.NotIn):
            return left not in right
        raise ValueError("unsupported_compare_operator")

    def _call_safe_function(
        self, name: str, args: list[Any], kwargs: dict[str, Any]
    ) -> Any:
        if name == "coalesce":
            for item in args:
                if item not in (None, "", [], {}):
                    return item
            return kwargs.get("default")
        if name == "default":
            if not args:
                return kwargs.get("default")
            return args[0] if args[0] not in (None, "", [], {}) else kwargs.get("default")
        if name == "format":
            if not args:
                return ""
            template = str(args[0])
            positional = tuple(args[1:])
            return template.format(*positional, **kwargs)
        if name == "concat":
            return "".join("" if item is None else str(item) for item in args)
        if name == "join":
            if not args:
                return ""
            separator = str(args[0])
            values = args[1] if len(args) > 1 else []
            if not isinstance(values, list):
                raise ValueError("join_requires_list")
            return separator.join("" if item is None else str(item) for item in values)
        if name == "length":
            if not args:
                return 0
            return len(args[0])
        if name == "lower":
            return str(args[0] if args else "").lower()
        if name == "upper":
            return str(args[0] if args else "").upper()
        if name == "contains":
            if len(args) < 2:
                return False
            container = args[0]
            target = args[1]
            if isinstance(container, (list, tuple, set, str, dict)):
                return target in container
            return False
        if name == "to_json":
            return json.dumps(args[0] if args else None, ensure_ascii=False, default=str)
        raise ValueError(f"unsupported_expression_function:{name}")

    @staticmethod
    def _resolve_attr_or_key(value: Any, key: Any) -> Any:
        if isinstance(value, dict):
            if key in value:
                return value[key]
            raise ValueError(f"expression_key_not_found:{key}")
        if isinstance(value, list):
            if isinstance(key, int):
                return value[key]
            raise ValueError(f"expression_list_index_invalid:{key}")
        if hasattr(value, key):
            return getattr(value, key)
        raise ValueError(f"expression_attr_not_found:{key}")

    @staticmethod
    def _match_expr(match: re.Match[str]) -> str:
        return next(
            group.strip() for group in match.groups() if isinstance(group, str)
        )

    @staticmethod
    def coerce_int(value: Any) -> int | None:
        """把模板里的松散 ID 字段收敛成 int。"""

        try:
            return None if value in (None, "") else int(value)
        except Exception:
            return None

    @staticmethod
    def json_safe(payload: Any) -> Any:
        """把复杂对象收敛成可落库 JSON。"""

        try:
            return json.loads(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            return payload
