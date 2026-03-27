"""HTTP 接口执行模型。

这层模型的作用是把 agent 产生的 HTTP 调用计划收敛成稳定的结构化协议，
避免工具层只靠自由文本拼装请求，后续也方便做审计、模板沉淀和审批判断。
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class HttpFilePart(BaseModel):
    """描述 multipart 上传里的单个文件字段。"""

    field_name: str = Field(..., description="表单中的文件字段名")
    file_id: str = Field(..., description="平台已登记文件 ID")
    filename: Optional[str] = Field(default=None, description="上传时使用的文件名")
    content_type: Optional[str] = Field(default=None, description="上传文件 MIME 类型")


class HttpDownloadConfig(BaseModel):
    """描述文件下载行为。"""

    enabled: bool = Field(default=False, description="是否启用下载模式")
    output_filename: Optional[str] = Field(
        default=None,
        description="固定输出文件名；为空时从响应头或 URL 推断",
    )
    output_dir: str = Field(
        default="output/http_downloads",
        description="下载文件落到 workspace 的相对目录",
    )


class HttpRequestSpec(BaseModel):
    """结构化 HTTP 请求计划。"""

    url: str = Field(..., description="目标 URL")
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(default="GET")
    headers: Dict[str, str] = Field(default_factory=dict)
    query_params: Dict[str, Any] = Field(default_factory=dict)
    json_body: Optional[Dict[str, Any] | List[Any]] = Field(default=None)
    form_fields: Dict[str, Any] = Field(default_factory=dict)
    raw_body: Optional[str] = Field(default=None)
    file_parts: List[HttpFilePart] = Field(default_factory=list)
    auth_type: Optional[Literal["bearer", "basic", "api_key", "api_key_query"]] = Field(
        default=None
    )
    auth_token: Optional[str] = Field(default=None)
    api_key_param: str = Field(default="api_key")
    timeout: int = Field(default=30)
    retry_count: int = Field(default=1)
    allow_redirects: bool = Field(default=True)
    download: HttpDownloadConfig = Field(default_factory=HttpDownloadConfig)
    response_extract: Dict[str, Any] = Field(
        default_factory=dict,
        description="响应提取规则，例如 fields/data_path/message_path/summary_template",
    )


class HttpExecutionResult(BaseModel):
    """HTTP 执行结果。

    对 agent / orchestrator 暴露的是结构化结果，而不是底层 httpx Response，
    这样后续 trace、账本和用户消息都更好消费。
    """

    success: bool
    status_code: int
    headers: Dict[str, str] = Field(default_factory=dict)
    body: Any = None
    error: Optional[str] = None
    downloaded_file_id: Optional[str] = None
    downloaded_file_path: Optional[str] = None
    extracted_fields: Dict[str, Any] = Field(default_factory=dict)
    summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
