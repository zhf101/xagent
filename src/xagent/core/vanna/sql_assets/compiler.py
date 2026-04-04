"""SQL Asset 模板编译器。"""

from __future__ import annotations

import re
from typing import Any


class SqlTemplateCompiler:
    """把 SQL 模板编译成可执行 SQL 和 bound params。"""

    _if_block_pattern = re.compile(
        r"{%\s*if\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*%}(.*?){%\s*endif\s*%}",
        re.DOTALL,
    )
    _placeholder_pattern = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")

    def compile(
        self,
        *,
        template_sql: str,
        parameter_schema_json: list[dict[str, Any]],
        render_config_json: dict[str, Any],
        bound_params: dict[str, Any],
    ) -> dict[str, Any]:
        del parameter_schema_json, render_config_json
        normalized_sql = str(template_sql or "").strip()
        if not normalized_sql:
            raise ValueError("template_sql cannot be empty")

        working_sql = self._render_conditionals(
            template_sql=normalized_sql,
            bound_params=bound_params,
        )
        compiled_params: dict[str, Any] = {}

        def replace_placeholder(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in bound_params:
                raise ValueError(f"Missing bound parameter: {name}")
            value = bound_params[name]
            if isinstance(value, list):
                if not value:
                    raise ValueError(f"Array parameter {name} cannot be empty")
                placeholders: list[str] = []
                for index, item in enumerate(value):
                    expanded_name = f"{name}_{index}"
                    compiled_params[expanded_name] = item
                    placeholders.append(f":{expanded_name}")
                return "(" + ", ".join(placeholders) + ")"

            compiled_params[name] = value
            return f":{name}"

        compiled_sql = self._placeholder_pattern.sub(replace_placeholder, working_sql)
        return {
            "compiled_sql": compiled_sql,
            "bound_params": compiled_params,
        }

    def _render_conditionals(
        self, *, template_sql: str, bound_params: dict[str, Any]
    ) -> str:
        def replace_if_block(match: re.Match[str]) -> str:
            name = match.group(1)
            content = match.group(2)
            value = bound_params.get(name)
            if value in (None, "", [], {}):
                return ""
            return content

        previous = template_sql
        while True:
            rendered = self._if_block_pattern.sub(replace_if_block, previous)
            if rendered == previous:
                return rendered
            previous = rendered
