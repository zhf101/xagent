"""MCP 模板步骤执行器。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from xagent.core.tools.core.mcp.sessions import create_session

from ..context import TemplateRuntimeContext
from ..models import TemplateRuntimeStep, TemplateStepResult
from .base import TemplateStepExecutor


class McpTemplateStepExecutor(TemplateStepExecutor):
    """MCP 真执行器。

    这层直接复用现有 MCP session 基础设施，不重新发明 transport / session 管理。
    runtime 只做：
    - server/tool 本地预检
    - tool_args 渲染
    - session.initialize + call_tool 真调用
    - 结果归一化，方便账本和后续步骤引用
    """

    kind = "mcp"

    def validate(self, step: TemplateRuntimeStep, context: TemplateRuntimeContext) -> None:
        self._prepare_call(step, context, strict_steps=False)

    def prepare(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateRuntimeStep:
        call_plan = self._prepare_call(step, context, strict_steps=True)
        return replace(
            step,
            input_data={
                "server_name": call_plan["server_name"],
                "tool_name": call_plan["tool_name"],
                "tool_args": context.json_safe(call_plan["tool_args"]),
            },
            config=call_plan,
        )

    async def execute(
        self, step: TemplateRuntimeStep, context: TemplateRuntimeContext
    ) -> TemplateStepResult:
        server_name = str(step.config["server_name"])
        tool_name = str(step.config["tool_name"])
        tool_args = dict(step.config["tool_args"])
        connection = context.get_mcp_connection(server_name)
        if connection is None:
            payload = {
                "success": False,
                "server_name": server_name,
                "tool_name": tool_name,
                "error": f"mcp_server_not_found:{server_name}",
            }
            return TemplateStepResult(
                success=False,
                output=f"mcp_server_not_found:{server_name}",
                output_data=payload,
                error_message=f"mcp_server_not_found:{server_name}",
            )

        try:
            async with create_session(connection) as session:
                await session.initialize()

                available_tools = None
                try:
                    tools_result = await session.list_tools()
                    tools = tools_result.tools if tools_result.tools else []
                    available_tools = {tool.name for tool in tools}
                except Exception:
                    available_tools = None

                if available_tools is not None and tool_name not in available_tools:
                    payload = {
                        "success": False,
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "tool_args": context.json_safe(tool_args),
                        "error": f"mcp_tool_not_found:{tool_name}",
                    }
                    return TemplateStepResult(
                        success=False,
                        output=f"mcp_tool_not_found:{tool_name}",
                        output_data=payload,
                        error_message=f"mcp_tool_not_found:{tool_name}",
                    )

                result = await session.call_tool(tool_name, tool_args)

            content = self._normalize_content(
                result.content if result.content else [],
                context,
            )
            text_parts = [
                str(item.get("text"))
                for item in content
                if isinstance(item, dict) and item.get("text") not in (None, "")
            ]
            is_error = bool(getattr(result, "isError", False))
            payload = {
                "success": not is_error,
                "server_name": server_name,
                "tool_name": tool_name,
                "tool_args": context.json_safe(tool_args),
                "content": content,
                "is_error": is_error,
                "output": "\n".join(text_parts)
                if text_parts
                else f"MCP {server_name}/{tool_name} executed",
                "summary": (
                    f"MCP {server_name}/{tool_name} executed successfully."
                    if not is_error
                    else f"MCP {server_name}/{tool_name} failed."
                ),
            }
            return TemplateStepResult(
                success=not is_error,
                output=str(payload["output"]),
                summary=str(payload["summary"]),
                output_data=context.json_safe(payload),
                error_message=None if not is_error else str(payload["output"]),
            )
        except Exception as exc:
            payload = {
                "success": False,
                "server_name": server_name,
                "tool_name": tool_name,
                "tool_args": context.json_safe(tool_args),
                "error": str(exc),
            }
            return TemplateStepResult(
                success=False,
                output=str(exc),
                output_data=payload,
                error_message=str(exc),
            )

    def _prepare_call(
        self,
        step: TemplateRuntimeStep,
        context: TemplateRuntimeContext,
        *,
        strict_steps: bool,
    ) -> dict[str, Any]:
        server_name = str(step.raw_step.get("server_name") or "").strip()
        tool_name = str(step.raw_step.get("tool_name") or "").strip()
        if not server_name:
            raise ValueError("mcp_step_missing_server_name")
        if not tool_name:
            raise ValueError("mcp_step_missing_tool_name")
        if context.get_mcp_connection(server_name) is None:
            raise ValueError(f"mcp_server_not_found:{server_name}")

        tool_args = context.render_value(
            step.raw_step.get("tool_args") or {},
            allow_step_refs=True,
            strict_steps=strict_steps,
        )
        if not isinstance(tool_args, dict):
            raise ValueError("mcp_step_tool_args_must_render_to_object")
        if context.contains_unresolved_placeholders(
            tool_args,
            allow_step_refs=not strict_steps,
        ):
            raise ValueError("mcp_step_has_unresolved_placeholders")

        return {
            "server_name": server_name,
            "tool_name": tool_name,
            "tool_args": context.json_safe(tool_args),
        }

    @staticmethod
    def _normalize_content(
        content_items: list[Any],
        context: TemplateRuntimeContext,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in content_items:
            if hasattr(item, "model_dump"):
                normalized.append(context.json_safe(item.model_dump()))
            elif isinstance(item, dict):
                normalized.append(context.json_safe(item))
            else:
                normalized.append({"text": str(item)})
        return normalized
