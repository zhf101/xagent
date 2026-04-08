"""
从 Mock API (http://127.0.0.1:18080) 导入 OpenAPI 规范到 GDP HTTP 资产。

该脚本会：
1. 获取 Mock API 的 OpenAPI 规范
2. 将每个接口转换为 GdpHttpAssetUpsertRequest 格式
3. 通过 GdpHttpResourceService 创建资产

使用方法：
    python -m scripts.import_mockapi_to_gdp_http
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from sqlalchemy.orm import Session

# 延迟导入避免循环导入
# from xagent.core.gdp.http_asset_protocol import (
#     GdpHttpAssetResource,
#     GdpHttpAssetUpsertRequest,
#     GdpHttpExecutionProfile,
#     GdpHttpToolContract,
# )
# from xagent.core.gdp.application.http_resource_service import GdpHttpResourceService
# from xagent.web.models.database import init_db, get_session_local
# from xagent.web.models.user import User

# 直接使用数据库操作避免循环导入
from xagent.web.models.database import init_db, get_session_local


# Mock API 基础配置
MOCK_API_BASE_URL = "http://127.0.0.1:18080"
OPENAPI_URL = f"{MOCK_API_BASE_URL}/openapi.json"

# 默认用户 ID（需要数据库中存在）
DEFAULT_USER_ID = 1
SUPPORTED_HTTP_METHODS = {"GET", "POST"}


def fetch_openapi_spec() -> dict[str, Any]:
    """获取 OpenAPI 规范。"""
    print(f"正在获取 OpenAPI 规范: {OPENAPI_URL}")
    response = httpx.get(OPENAPI_URL, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_args_position(
    parameters: list[dict[str, Any]],
    request_body: dict[str, Any] | None,
    components: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    从 OpenAPI 参数列表中提取参数位置信息。
    
    返回结构（符合 GdpHttpAssetValidator 要求）：
    {
        "source_path": {"in": "path/query/header/body", "name": "参数名", ...},
    }
    
    其中 source_path 是 input_schema 中的属性路径（如 "id" 或 "item_id"）。
    
    注意：cookie 参数暂不支持，会被跳过。
    """
    args_position: dict[str, dict[str, Any]] = {}
    
    for param in parameters:
        param_in = param.get("in", "query")
        param_name = param.get("name")
        if not param_name:
            continue
        
        # GDP HTTP 资产不支持 cookie 参数，跳过
        # 后续可通过 auth_json 或其他方式处理
        if param_in == "cookie":
            continue
        
        # source_path 就是参数名（顶层参数）
        source_path = param_name
        
        route: dict[str, Any] = {"in": param_in, "name": param_name}
        
        # 记录是否必填
        if param.get("required"):
            route["required"] = True
        
        args_position[source_path] = route
    
    # 处理请求体
    if request_body:
        content = request_body.get("content", {})

        # text/plain 直接交给 request_template.body，不额外声明 body 路由，
        # 否则会与当前 GDP validator 的“body 模板和 body 路由互斥”规则冲突。
        if "text/plain" in content:
            return args_position

        for content_type in (
            "application/json",
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        ):
            if content_type not in content:
                continue
            schema = content[content_type].get("schema", {})
            resolved_schema = resolve_schema(schema, components)
            if resolved_schema.get("type") != "object":
                args_position["body"] = {"in": "body", "name": "body"}
            break
    
    return args_position


def build_input_schema(
    method: str,
    parameters: list[dict[str, Any]],
    request_body: dict[str, Any] | None,
    components: dict[str, Any],
) -> dict[str, Any]:
    """
    构建 MCP 工具的 input_schema_json。
    
    将 OpenAPI 的参数和请求体转换为 JSON Schema 格式。
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    
    # 处理 parameters
    for param in parameters:
        param_name = param.get("name")
        param_in = param.get("in", "query")
        if not param_name:
            continue
        
        # 跳过 cookie 参数（不支持）
        if param_in == "cookie":
            continue
        
        # 解析 schema（可能包含 $ref）
        schema = resolve_schema(param.get("schema", {}), components)
        
        # 添加描述
        if param.get("description"):
            schema["description"] = param["description"]

        properties[param_name] = schema
        
        if param.get("required", False):
            required.append(param_name)
    
    # 处理 request body
    if request_body:
        content = request_body.get("content", {})
        
        # 处理 JSON 请求体
        json_content = content.get("application/json", {})
        if json_content:
            body_schema = resolve_schema(json_content.get("schema", {}), components)
            
            # 如果请求体是对象，将其属性合并到 input schema
            if body_schema.get("type") == "object":
                for prop_name, prop_schema in body_schema.get("properties", {}).items():
                    if prop_name not in properties:  # 避免覆盖同名参数
                        properties[prop_name] = prop_schema
                if request_body.get("required"):
                    required.extend(body_schema.get("required", []))
            # 非对象类型：添加 body 字段，用于接收整个请求体
            else:
                properties["body"] = body_schema
                if request_body.get("required"):
                    required.append("body")
        
        # 处理表单请求体
        form_content = content.get("application/x-www-form-urlencoded", {})
        if form_content:
            body_schema = resolve_schema(form_content.get("schema", {}), components)
            if body_schema.get("type") == "object":
                for prop_name, prop_schema in body_schema.get("properties", {}).items():
                    if prop_name not in properties:
                        properties[prop_name] = prop_schema
                if request_body.get("required"):
                    required.extend(body_schema.get("required", []))
        
        # 处理 multipart 文件上传
        multipart_content = content.get("multipart/form-data", {})
        if multipart_content:
            body_schema = resolve_schema(multipart_content.get("schema", {}), components)
            if body_schema.get("type") == "object":
                for prop_name, prop_schema in body_schema.get("properties", {}).items():
                    if prop_name not in properties:
                        properties[prop_name] = prop_schema
                if request_body.get("required"):
                    required.extend(body_schema.get("required", []))
        
        # 处理纯文本请求体
        text_content = content.get("text/plain", {})
        if text_content:
            body_schema = resolve_schema(text_content.get("schema", {}), components)
            properties["body"] = body_schema
            if request_body.get("required"):
                required.append("body")
    
    return {
        "type": "object",
        "properties": properties,
        "required": list(set(required)),  # 去重
    }


def resolve_schema(schema: dict[str, Any], components: dict[str, Any]) -> dict[str, Any]:
    """解析 schema 中的 $ref 引用。"""
    if not schema:
        return {}
    
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/components/schemas/"):
            schema_name = ref.replace("#/components/schemas/", "")
            resolved = components.get("schemas", {}).get(schema_name, {})
            # 递归解析嵌套的 $ref
            return resolve_schema(resolved, components)
        return schema
    
    # 处理 anyOf
    if "anyOf" in schema:
        # 取第一个非 null 的类型
        for variant in schema["anyOf"]:
            if variant.get("type") != "null":
                return resolve_schema(variant, components)
        return schema
    
    # 处理 allOf
    if "allOf" in schema:
        merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
        for subschema in schema["allOf"]:
            resolved = resolve_schema(subschema, components)
            merged["properties"].update(resolved.get("properties", {}))
            merged["required"].extend(resolved.get("required", []))
        return merged
    
    # 处理 oneOf
    if "oneOf" in schema:
        # 简化处理，返回联合类型描述
        return {"type": "object", "description": "oneOf 类型，请参考原始 API 文档"}
    
    # 递归处理嵌套属性
    if "properties" in schema:
        resolved_props = {}
        for prop_name, prop_schema in schema["properties"].items():
            resolved_props[prop_name] = resolve_schema(prop_schema, components)
        schema = {**schema, "properties": resolved_props}
    
    # 处理 items
    if "items" in schema:
        schema = {**schema, "items": resolve_schema(schema["items"], components)}
    
    return schema


def build_output_schema(
    responses: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    """构建 MCP 工具的 output_schema_json。"""
    # 获取成功响应的 schema
    success_response = responses.get("200") or responses.get("201") or responses.get("202")
    if not success_response:
        return {"type": "object", "description": "响应结构未知"}
    
    content = success_response.get("content", {})
    
    # JSON 响应
    json_content = content.get("application/json", {})
    if json_content:
        schema = json_content.get("schema", {})
        return resolve_schema(schema, components)
    
    # 文本响应
    text_content = content.get("text/plain", {})
    if text_content:
        return {"type": "string", "description": "纯文本响应"}
    
    return {"type": "object", "description": "响应结构未知"}


def build_request_template(
    method: str,
    parameters: list[dict[str, Any]],
    request_body: dict[str, Any] | None,
) -> dict[str, Any]:
    """构建当前 GDP HTTP runtime 可执行的 request_template_json。"""

    normalized_method = str(method or "GET").upper()
    template: dict[str, Any] = {"method": normalized_method}

    headers: list[dict[str, str]] = []

    if request_body:
        content = request_body.get("content", {})
        if "application/json" in content:
            headers.append({"key": "Content-Type", "value": "application/json"})
            template["argsToJsonBody"] = True
        elif "application/x-www-form-urlencoded" in content:
            headers.append(
                {
                    "key": "Content-Type",
                    "value": "application/x-www-form-urlencoded",
                }
            )
            template["argsToJsonBody"] = True
        elif "multipart/form-data" in content:
            headers.append({"key": "Content-Type", "value": "multipart/form-data"})
            template["argsToJsonBody"] = True
        elif "text/plain" in content:
            headers.append({"key": "Content-Type", "value": "text/plain"})
            template["body"] = "{{ args.body }}"
    elif normalized_method == "GET":
        template["argsToUrlParam"] = True
    else:
        has_only_non_body_params = any(
            param.get("in") in {"query", "path", "header"} for param in parameters
        )
        if has_only_non_body_params:
            template["argsToUrlParam"] = True

    if headers:
        template["headers"] = headers

    return template


def convert_openapi_to_gdp_asset(
    path: str,
    method: str,
    operation: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    """
    将单个 OpenAPI operation 转换为 GdpHttpAssetUpsertRequest。
    
    关键字段映射：
    - resource_key: mockapi_{operationId}
    - system_short: mockapi
    - tool_name: operationId
    - tool_description: summary + description
    - method: HTTP 方法
    - url_mode: direct
    - direct_url: 基础URL + path
    - args_position_json: 参数位置映射
    - input_schema_json: 输入 schema
    - output_schema_json: 输出 schema
    
    返回字典格式，避免循环导入。
    """
    return convert_openapi_to_gdp_asset_dict(path, method, operation, components)


def convert_openapi_to_gdp_asset_dict(
    path: str,
    method: str,
    operation: dict[str, Any],
    components: dict[str, Any],
) -> dict[str, Any]:
    """
    将单个 OpenAPI operation 转换为 GdpHttpResource 模型字段。
    
    返回字典格式，包含所有表字段。
    """
    operation_id = operation.get("operationId", f"{method.lower()}_{path.replace('/', '_')}")
    summary = operation.get("summary", operation_id)
    description = operation.get("description", summary)
    parameters = operation.get("parameters", [])
    request_body = operation.get("requestBody")
    responses = operation.get("responses", {})
    tags = operation.get("tags", [])
    
    # 提取参数位置信息
    args_position = extract_args_position(parameters, request_body, components)
    
    # 构建输入 schema
    input_schema = build_input_schema(method, parameters, request_body, components)
    
    # 构建输出 schema
    output_schema = build_output_schema(responses, components)
    
    # 构建请求模板
    request_template = build_request_template(method, parameters, request_body)
    
    # 构建 resource_key
    resource_key = f"mockapi_{operation_id}"
    
    # 构建 tool_description（合并 summary 和 description）
    tool_description = f"{summary}"
    if description and description != summary:
        tool_description = f"{summary}: {description}"
    
    # 返回完整的字段字典（只包含实际表字段）
    return {
        "resource_key": resource_key,
        "system_short": "mockapi",
        "visibility": "global",
        "summary": summary,
        "tags_json": tags,
        "tool_name": operation_id,
        "tool_description": tool_description,
        "input_schema_json": input_schema,
        "output_schema_json": output_schema,
        "annotations_json": {},
        "method": method.upper(),
        "url_mode": "direct",
        "direct_url": f"{MOCK_API_BASE_URL}{path}",
        "sys_label": None,
        "url_suffix": None,
        "args_position_json": args_position,
        "request_template_json": request_template,
        "response_template_json": {},
        "error_response_template": None,
        "auth_json": {},
        "headers_json": {},
        "timeout_seconds": 30,
    }


def import_all_assets(db: Session, user_id: int) -> list[dict[str, Any]]:
    """
    导入所有 OpenAPI 接口到 GDP HTTP 资产。
    
    返回导入结果列表。
    """
    # 延迟导入避免循环导入
    from xagent.web.models.gdp_http_resource import GdpHttpResource
    from xagent.web.models.user import User
    
    # 获取 OpenAPI 规范
    openapi_spec = fetch_openapi_spec()
    paths = openapi_spec.get("paths", {})
    components = openapi_spec.get("components", {})
    
    print(f"发现 {len(paths)} 个路径")
    
    # 获取用户
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"用户 ID {user_id} 不存在")
    
    user_name = getattr(user, "username", None) or getattr(user, "name", None)
    
    results: list[dict[str, Any]] = []
    
    for path, path_item in paths.items():
        for method in ["get", "post", "put", "patch", "delete"]:
            if method not in path_item:
                continue
            
            operation = path_item[method]
            operation_id = operation.get("operationId", f"{method}_{path}")
            normalized_method = method.upper()

            if normalized_method not in SUPPORTED_HTTP_METHODS:
                results.append(
                    {
                        "status": "skipped",
                        "resource_key": f"mockapi_{operation_id}",
                        "method": normalized_method,
                        "path": path,
                        "reason": "unsupported_method",
                    }
                )
                print(f"  - 跳过: {normalized_method} {path} (当前仅支持 GET/POST)")
                continue
            
            print(f"正在导入: {normalized_method} {path} ({operation_id})")
            
            try:
                # 转换为资产数据
                payload_dict = convert_openapi_to_gdp_asset_dict(
                    path=path,
                    method=normalized_method,
                    operation=operation,
                    components=components,
                )
                
                # 检查是否已存在
                resource_key = payload_dict["resource_key"]
                existing = db.query(GdpHttpResource).filter(
                    GdpHttpResource.resource_key == resource_key
                ).first()
                
                if existing:
                    # 更新现有资产
                    for key, value in payload_dict.items():
                        setattr(existing, key, value)
                    db.commit()
                    db.refresh(existing)
                    asset = existing
                else:
                    # 创建新资产
                    asset = GdpHttpResource(
                        create_user_id=user_id,
                        create_user_name=user_name,
                        **payload_dict
                    )
                    db.add(asset)
                    db.commit()
                    db.refresh(asset)
                
                results.append({
                    "status": "success",
                    "resource_key": resource_key,
                    "asset_id": asset.id,
                    "method": normalized_method,
                    "path": path,
                })
                print(f"  ✓ 成功: asset_id={asset.id}")
                
            except Exception as e:
                import traceback
                db.rollback()
                results.append({
                    "status": "error",
                    "resource_key": f"mockapi_{operation_id}",
                    "method": normalized_method,
                    "path": path,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
                print(f"  ✗ 失败: {e}")
                print(f"  详细错误: {traceback.format_exc()}")
    
    return results


def main():
    """主入口。"""
    print("=" * 60)
    print("从 Mock API 导入 OpenAPI 规范到 GDP HTTP 资产")
    print("=" * 60)
    
    # 初始化数据库
    init_db()
    
    db: Session = get_session_local()()
    try:
        results = import_all_assets(db, DEFAULT_USER_ID)
        
        # 统计结果
        success_count = sum(1 for r in results if r["status"] == "success")
        error_count = sum(1 for r in results if r["status"] == "error")
        
        print("\n" + "=" * 60)
        print(f"导入完成: 成功 {success_count} 个, 失败 {error_count} 个")
        print("=" * 60)
        
        # 显示失败项
        if error_count > 0:
            print("\n失败项:")
            for r in results:
                if r["status"] == "error":
                    print(f"  - {r['method']} {r['path']}: {r['error']}")
        
    finally:
        db.close()


if __name__ == "__main__":
    main()
