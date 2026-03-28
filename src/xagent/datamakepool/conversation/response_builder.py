"""智能造数平台会话响应构造器。

职责：
- 把会话域对象统一格式化为前端可消费的 `task_completed` payload
- 避免 websocket 入口里散落大量 conversation metadata / ui / task 摘要拼装逻辑
"""

from __future__ import annotations

from typing import Any


class ConversationResponseBuilder:
    """构造智能造数平台会话响应。"""

    @staticmethod
    def build_task_completed_payload(
        *,
        task: Any,
        session: Any | None,
        success: bool,
        result_text: str,
        execution_type: str,
        chat_response: dict[str, Any] | None = None,
        ui: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = {
            "execution_type": execution_type,
            **ConversationResponseBuilder._conversation_metadata(session),
            **(extra_metadata or {}),
        }
        if ui and "ui_type" not in metadata:
            metadata["ui_type"] = ui.get("type")

        payload: dict[str, Any] = {
            "type": "task_completed",
            "task": {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "description": task.description,
            },
            "success": success,
            "result": result_text,
            "output": result_text,
            "metadata": metadata,
        }
        if chat_response is not None:
            payload["chat_response"] = chat_response
        if ui is not None:
            payload["ui"] = ui
        return payload

    @staticmethod
    def _conversation_metadata(session: Any | None) -> dict[str, Any]:
        if session is None:
            return {}
        return {
            "conversation_state": getattr(session, "state", None),
            "fact_snapshot": dict(getattr(session, "fact_snapshot", None) or {}),
            "latest_summary": getattr(session, "latest_summary", None),
            "active_decision_frame_id": getattr(session, "active_decision_frame_id", None),
            "active_execution_run_id": getattr(session, "active_execution_run_id", None),
        }
