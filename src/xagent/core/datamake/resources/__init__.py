"""
`Resource Plane`（资源平面）。

这一层负责把底层真实资源包装成“可治理、可枚举、可校验”的资源动作。
也就是说，runtime 不应该面对任意原始 SQL、任意自由 HTTP 请求，
而应该面对已经注册好的受控资源能力。
"""

from .http_resource_definition import (
    HttpArgRoute,
    HttpContextMaterialSet,
    HttpDatasourceBinding,
    HttpEndpointSpec,
    HttpHeaderTemplateItem,
    HttpInterfaceContract,
    HttpParameterDefinition,
    HttpResolvedResourceMetadata,
    HttpRequestTemplate,
    HttpResponseExtractionRule,
    HttpResponseTemplate,
    HttpResourceActionTemplate,
    HttpResourceMetadata,
    HttpSuccessPolicy,
    HttpToolSafetyHints,
    build_http_resource_action_definition,
    build_http_resource_action_payload,
    parse_http_resource_metadata,
)
from .http_conversion import HttpConversionEngine, HttpConvertedRequestParts
from .http_response_folder import HttpFoldedResponse, HttpResponseFolder
from .http_template_engine import HttpRenderedRequest, HttpTemplateEngine
from .sql_brain_gateway import SqlBrainGateway
from .sql_datasource_resolver import SqlDatasourceResolver
from .sql_resource_definition import (
    SqlResourceActionTemplate,
    SqlResourceMetadata,
    build_sql_resource_action_definition,
    build_sql_resource_action_payload,
)
from .sql_schema_provider import SqlSchemaProvider

__all__ = [
    "HttpArgRoute",
    "HttpContextMaterialSet",
    "HttpConvertedRequestParts",
    "HttpConversionEngine",
    "HttpDatasourceBinding",
    "HttpEndpointSpec",
    "HttpFoldedResponse",
    "HttpHeaderTemplateItem",
    "HttpInterfaceContract",
    "HttpParameterDefinition",
    "HttpRenderedRequest",
    "HttpResolvedResourceMetadata",
    "HttpRequestTemplate",
    "HttpResponseExtractionRule",
    "HttpResponseFolder",
    "HttpResponseTemplate",
    "HttpResourceActionTemplate",
    "HttpResourceMetadata",
    "HttpSuccessPolicy",
    "HttpTemplateEngine",
    "HttpToolSafetyHints",
    "build_http_resource_action_definition",
    "build_http_resource_action_payload",
    "parse_http_resource_metadata",
    "SqlBrainGateway",
    "SqlDatasourceResolver",
    "SqlResourceMetadata",
    "SqlResourceActionTemplate",
    "build_sql_resource_action_definition",
    "build_sql_resource_action_payload",
    "SqlSchemaProvider",
]
