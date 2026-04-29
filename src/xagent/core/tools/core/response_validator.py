"""HTTP 响应业务语义验证器。

这个模块只负责判断“协议请求已经完成后，业务是否真的成功”。
HTTP 客户端仍然负责网络、状态码、重试；业务验证器只读取已经解析好的
JSON/dict 响应体，并根据配置判断是否命中了业务失败规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BusinessValidationResult:
    """业务验证结果。

    `matched` 表示是否命中了显式失败规则。
    没有配置规则时，调用方应把业务状态视为“未知”，而不是失败。
    """

    matched: bool
    message: str | None = None
    is_terminal: bool = True
    matched_condition: dict[str, Any] | None = None


class ResponseBusinessValidator:
    """基于 JSON path 的业务失败规则验证器。

    支持的配置刻意保持小而明确：
    - `mode=success_conditions`：所有成功条件都满足才算业务成功，否则失败。
    - `mode=failure_conditions`：任一失败条件命中即判定业务失败。
    - `failure_conditions`：任一条件命中即判定业务失败。
    - `success_conditions`：全部条件命中才判定成功。
    - `path`：支持 `a.b[0].c` 和 `$.a.b[0].c` 两种常见写法。
    - `value`/`eq`：字段值等于指定值时失败。
    - `ne`：字段值不等于指定值时失败，适合 `code != 0`。
    - `exists`：字段是否存在，适合某些 API 只返回 error 字段的情况。

    这里不引入完整 JSONPath 依赖，是为了避免把运行时关键路径绑定到更重的
    表达式语义；当前需求只需要稳定支持对象字段和数组下标。
    """

    _DEFAULT_MESSAGE_PATHS = (
        "message",
        "msg",
        "err_msg",
        "error_message",
        "errorMsg",
        "error",
        "data.message",
        "data.msg",
        "data.err_msg",
        "data.error_message",
        "data.errorMsg",
        "data.error",
    )

    def validate(
        self,
        response_body: Any,
        rule: dict[str, Any] | None,
    ) -> BusinessValidationResult | None:
        """按规则验证响应体。

        返回 `None` 表示没有配置业务验证，不参与成败裁决。
        返回 `BusinessValidationResult(matched=False)` 表示已配置但未命中失败规则。
        """

        if not isinstance(rule, dict) or not rule:
            return None

        if str(rule.get("type") or "json_path") != "json_path":
            return BusinessValidationResult(
                matched=True,
                message=f"不支持的业务验证类型: {rule.get('type')}",
                is_terminal=True,
            )

        if not isinstance(response_body, (dict, list)):
            return BusinessValidationResult(
                matched=True,
                message="响应不是 JSON 对象/数组，无法执行业务失败判定",
                is_terminal=bool(rule.get("is_terminal", True)),
            )

        mode = str(rule.get("mode") or "failure_conditions").strip()
        if mode == "success_conditions":
            return self._validate_success_conditions(response_body, rule)

        conditions = rule.get("failure_conditions")
        if not isinstance(conditions, list) or not conditions:
            return BusinessValidationResult(
                matched=False,
                is_terminal=bool(rule.get("is_terminal", True)),
            )

        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            if self._condition_matches(response_body, condition):
                return BusinessValidationResult(
                    matched=True,
                    message=self.extract_message(response_body, rule),
                    is_terminal=bool(rule.get("is_terminal", True)),
                    matched_condition=dict(condition),
                )

        return BusinessValidationResult(
            matched=False,
            is_terminal=bool(rule.get("is_terminal", True)),
        )

    def _validate_success_conditions(
        self,
        response_body: Any,
        rule: dict[str, Any],
    ) -> BusinessValidationResult:
        """执行“必须证明成功”的白名单式业务判定。

        这种模式适合成功报文明确定义、失败形态很多的接口。只要任意成功条件
        不满足，就把 HTTP 2xx 响应视为业务失败，避免代理继续调用后续 API。
        """

        conditions = rule.get("success_conditions")
        if not isinstance(conditions, list) or not conditions:
            return BusinessValidationResult(
                matched=True,
                message=(
                    str(rule.get("default_failure_message") or "").strip()
                    or "未配置业务成功条件，无法确认接口业务执行成功"
                ),
                is_terminal=bool(rule.get("is_terminal", True)),
            )

        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            if not self._condition_matches(response_body, condition):
                return BusinessValidationResult(
                    matched=True,
                    message=(
                        self.extract_message(response_body, rule)
                        or str(rule.get("default_failure_message") or "").strip()
                        or "接口返回未满足业务成功条件"
                    ),
                    is_terminal=bool(rule.get("is_terminal", True)),
                    matched_condition=dict(condition),
                )

        return BusinessValidationResult(
            matched=False,
            is_terminal=bool(rule.get("is_terminal", True)),
        )

    def extract_message(self, response_body: Any, rule: dict[str, Any]) -> str | None:
        """从响应体里提取最适合直接告知用户的失败原因。"""

        paths: list[str] = []
        raw_message_paths = rule.get("message_paths")
        raw_message_path = rule.get("message_path")

        if isinstance(raw_message_paths, list):
            paths.extend(str(path) for path in raw_message_paths if str(path).strip())
        if isinstance(raw_message_path, str) and raw_message_path.strip():
            paths.append(raw_message_path)

        paths.extend(path for path in self._DEFAULT_MESSAGE_PATHS if path not in paths)

        for path in paths:
            value, exists = self.get_path_value(response_body, path)
            if exists and value not in (None, ""):
                return str(value)
        return None

    def _condition_matches(self, response_body: Any, condition: dict[str, Any]) -> bool:
        path = str(condition.get("path") or "").strip()
        if not path:
            return False

        value, exists = self.get_path_value(response_body, path)

        if "exists" in condition:
            return exists is bool(condition["exists"])

        if "ne" in condition:
            if not exists:
                return False
            return value != condition.get("ne")

        expected = condition.get("eq") if "eq" in condition else condition.get("value")
        if "eq" in condition or "value" in condition:
            return exists and value == expected

        return False

    def get_path_value(self, payload: Any, path: str) -> tuple[Any, bool]:
        """读取简单 JSON path 的值，同时返回字段是否真实存在。

        只返回值会把“字段不存在”和“字段存在但值为 None”混在一起；
        `code != 0` 这类规则需要明确区分这两种情况。
        """

        normalized = str(path or "").strip()
        if normalized == "$":
            return payload, True
        if normalized.startswith("$."):
            normalized = normalized[2:]

        current: Any = payload
        for token in self._parse_tokens(normalized):
            if isinstance(token, int):
                if not isinstance(current, list) or token < 0 or token >= len(current):
                    return None, False
                current = current[token]
                continue
            if not isinstance(current, dict) or token not in current:
                return None, False
            current = current[token]
        return current, True

    def _parse_tokens(self, path: str) -> list[str | int]:
        tokens: list[str | int] = []
        current = ""
        index = 0
        while index < len(path):
            char = path[index]
            if char == ".":
                if current:
                    tokens.append(current)
                    current = ""
                index += 1
                continue
            if char == "[":
                if current:
                    tokens.append(current)
                    current = ""
                end = path.find("]", index)
                if end == -1:
                    return tokens
                raw_index = path[index + 1 : end].strip()
                if raw_index.isdigit():
                    tokens.append(int(raw_index))
                index = end + 1
                continue
            current += char
            index += 1

        if current:
            tokens.append(current)
        return tokens
