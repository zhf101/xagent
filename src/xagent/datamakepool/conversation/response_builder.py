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
    def build_task_paused_payload(
        *,
        task: Any,
        session: Any | None,
        message: str,
        approval: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "task_paused",
            "task": {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "description": task.description,
            },
            "success": False,
            "message": message,
            "output": message,
            "metadata": {
                **ConversationResponseBuilder._conversation_metadata(session),
                **(metadata or {}),
            },
        }
        if approval is not None:
            payload["approval"] = approval
        return payload

    @staticmethod
    def merge_execution_result_metadata(
        *,
        session: Any | None,
        execution_type: str,
        base_metadata: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把会话元数据与执行结果元数据合并成稳定输出。"""

        return {
            **(base_metadata or {}),
            "execution_type": execution_type,
            **ConversationResponseBuilder._conversation_metadata(session),
            **(extra_metadata or {}),
        }

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
            "decision_rationale": getattr(
                getattr(session, "active_decision_frame", None), "rationale", None
            ),
            "decision_recommended_action": getattr(
                getattr(session, "active_decision_frame", None),
                "recommended_action",
                None,
            ),
        }
