"""HTTP 响应提取器。"""

from __future__ import annotations

from typing import Any


def _get_by_path(payload: Any, path: str | None) -> Any:
    if not path:
        return None
    current = payload
    for segment in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        if isinstance(current, list):
            if not segment.isdigit():
                return None
            index = int(segment)
            if index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def extract_http_response(
    body: Any,
    response_extract: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    """按轻量规则从 HTTP 响应中提取字段和摘要。"""

    config = response_extract or {}
    extracted_fields: dict[str, Any] = {}

    fields = config.get("fields") or {}
    if isinstance(fields, dict):
        for alias, path in fields.items():
            extracted_fields[str(alias)] = _get_by_path(body, str(path))

    data_path = config.get("data_path")
    if data_path:
        extracted_fields["data"] = _get_by_path(body, str(data_path))

    message_path = config.get("message_path")
    if message_path:
        extracted_fields["message"] = _get_by_path(body, str(message_path))

    success_path = config.get("success_path")
    if success_path:
        extracted_fields["success_flag"] = _get_by_path(body, str(success_path))

    summary = None
    summary_template = config.get("summary_template")
    if summary_template and isinstance(summary_template, str):
        try:
            summary = summary_template.format(**extracted_fields)
        except Exception:
            summary = None
    elif "message" in extracted_fields and extracted_fields["message"] is not None:
        summary = str(extracted_fields["message"])

    return extracted_fields, summary
