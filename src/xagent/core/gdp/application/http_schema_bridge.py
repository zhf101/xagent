"""前端可视化 HTTP schema tree 与后端 payload 之间的桥接。"""

from __future__ import annotations

from typing import Any

from ..http_asset_protocol import GdpHttpVisualSchemaNode


def build_schema_and_routes_from_tree(
    tree: list[GdpHttpVisualSchemaNode],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """把前端 schema tree 转成 input_schema_json + args_position_json。

    这里刻意保持与前端历史 `schema-bridge.ts` 相同的数据展开方式，
    让 visual 编辑态在迁移到后端归一化接口后，不改变既有页面语义。
    """

    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    args_position: dict[str, dict[str, Any]] = {}

    def walk(
        nodes: list[GdpHttpVisualSchemaNode],
        parent_path: str = "",
    ) -> tuple[dict[str, Any], list[str]]:
        properties: dict[str, Any] = {}
        required: list[str] = []

        for node in nodes:
            current_path = (
                f"{parent_path}.{node.name}" if parent_path else node.name
            )

            schema: dict[str, Any] = {
                "type": node.type,
                "description": node.description,
            }

            if node.defaultValue:
                schema["default"] = node.defaultValue
            if node.enum:
                schema["enum"] = list(node.enum)
            if node.pattern:
                schema["pattern"] = node.pattern

            if node.type == "object" and node.children:
                child_properties, child_required = walk(node.children, current_path)
                schema["properties"] = child_properties
                if child_required:
                    schema["required"] = child_required
            elif node.type == "array" and node.children:
                item_node = node.children[0]
                item_properties, _ = walk([item_node], f"{current_path}[0]")
                schema["items"] = item_properties[item_node.name]

            properties[node.name] = schema
            if node.required:
                required.append(node.name)

            if node.route:
                args_position[current_path] = dict(node.route)

        return properties, required

    properties, required = walk(tree)
    input_schema["properties"] = properties
    input_schema["required"] = required
    return input_schema, args_position
