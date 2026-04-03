"""SQL 数据库连接表单与 URL 编解码能力。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit, urlunsplit

from xagent.core.utils.security import redact_sensitive_text

from .profiles import get_database_profile
from .types import normalize_database_type


def _clean_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_optional_string(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _clean_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_extra_params(raw_value: Any) -> dict[str, str]:
    if raw_value is None:
        return {}
    if isinstance(raw_value, dict):
        return {
            _clean_string(key): _clean_string(value)
            for key, value in raw_value.items()
            if _clean_string(key)
        }
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return {}
        pairs: dict[str, str] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key:
                pairs[key] = value
        return pairs
    return {}


def _encode_query(query: dict[str, Any]) -> str:
    filtered = {}
    for key, value in query.items():
        if value in (None, ""):
            continue
        filtered[str(key)] = str(value)
    return urlencode(filtered, doseq=True)


def _build_network_url(
    *,
    scheme: str,
    host: str,
    port: int | None = None,
    username: str | None = None,
    password: str | None = None,
    path: str | None = None,
    query: dict[str, Any] | None = None,
) -> str:
    netloc = ""
    encoded_username = quote(username or "", safe="")
    encoded_password = quote(password or "", safe="")

    if encoded_username:
        netloc += encoded_username
        if password is not None:
            netloc += f":{encoded_password}"
        netloc += "@"

    netloc += host
    if port is not None:
        netloc += f":{port}"

    normalized_path = ""
    if path:
        normalized_path = f"/{path.lstrip('/')}"

    query_string = _encode_query(query or {})
    return urlunsplit((scheme, netloc, normalized_path, query_string, ""))


def _build_sqlite_url(file_path: str, query: dict[str, Any] | None = None) -> str:
    normalized = file_path.replace("\\", "/").strip()
    if not normalized:
        raise ValueError("SQLite 文件路径不能为空")
    query_string = _encode_query(query or {})
    if len(normalized) >= 3 and normalized[1:3] == ":/":
        base = f"sqlite:///{normalized}"
    elif normalized.startswith("/"):
        base = f"sqlite://{normalized}"
    else:
        base = f"sqlite:///{normalized}"
    return f"{base}?{query_string}" if query_string else base


def _split_url_query(url: str) -> dict[str, str]:
    return {
        key: values[-1]
        for key, values in parse_qs(urlsplit(url).query, keep_blank_values=True).items()
        if values
    }


def _extract_scheme_base(url: str) -> str:
    raw_scheme = urlsplit(url).scheme
    return raw_scheme.split("+", 1)[0].lower()


def _extract_path_value(url: str) -> str:
    path = unquote(urlsplit(url).path or "")
    return path.lstrip("/")


def mask_connection_url(url: str) -> str:
    """对连接 URL 做最小必要脱敏。"""

    if not url:
        return url

    parsed = urlsplit(url)
    username = parsed.username or ""
    password = parsed.password or ""
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""

    netloc = parsed.netloc
    if password:
        password_mask = "***"
        if username:
            netloc = f"{quote(username, safe='')}:{password_mask}@{hostname}{port}"
        else:
            netloc = f":{password_mask}@{hostname}{port}"

    masked = urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )
    return redact_sensitive_text(masked)


@dataclass(frozen=True)
class ConnectionFieldOption:
    value: str
    label: str


@dataclass(frozen=True)
class ConnectionFieldDefinition:
    key: str
    label: str
    input_type: str = "text"
    required: bool = False
    placeholder: str | None = None
    description: str | None = None
    default_value: str | None = None
    advanced: bool = False
    secret: bool = False
    options: tuple[ConnectionFieldOption, ...] = field(default_factory=tuple)
    show_when: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["options"] = [asdict(item) for item in self.options]
        return payload


def _options(*pairs: tuple[str, str]) -> tuple[ConnectionFieldOption, ...]:
    return tuple(ConnectionFieldOption(value=value, label=label) for value, label in pairs)


def _base_network_fields(profile: dict[str, Any]) -> list[ConnectionFieldDefinition]:
    return [
        ConnectionFieldDefinition(
            key="host",
            label="主机/IP",
            required=True,
            placeholder="例如：127.0.0.1",
        ),
        ConnectionFieldDefinition(
            key="port",
            label="端口",
            input_type="number",
            required=bool(profile.get("default_port")),
            default_value=str(profile.get("default_port") or ""),
        ),
        ConnectionFieldDefinition(
            key="username",
            label="用户名",
            placeholder="例如：root",
        ),
        ConnectionFieldDefinition(
            key="password",
            label="密码",
            input_type="password",
            secret=True,
        ),
    ]


def get_connection_form_definition(db_type: str) -> dict[str, Any]:
    """返回指定 SQL 数据库类型的普通模式表单定义。"""

    normalized = normalize_database_type(db_type)
    profile = get_database_profile(normalized)
    fields: list[ConnectionFieldDefinition]

    if normalized in {"mysql", "oceanbase", "tidb", "polardb", "goldendb"}:
        fields = [
            *_base_network_fields(profile),
            ConnectionFieldDefinition(
                key="database",
                label="数据库名",
                required=True,
                placeholder="例如：crm",
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：charset=utf8mb4\nssl=true",
                description="每行一个 key=value，会拼接到 URL query 参数中",
            ),
        ]
    elif normalized in {"postgresql", "kingbase", "gaussdb", "vastbase", "highgo"}:
        fields = [
            *_base_network_fields(profile),
            ConnectionFieldDefinition(
                key="database",
                label="数据库名",
                required=True,
                placeholder="例如：analytics",
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：sslmode=require",
                description="每行一个 key=value",
            ),
        ]
    elif normalized == "sqlserver":
        fields = [
            *_base_network_fields(profile),
            ConnectionFieldDefinition(
                key="database",
                label="数据库名",
                required=True,
                placeholder="例如：master",
            ),
            ConnectionFieldDefinition(
                key="driver_mode",
                label="连接驱动",
                input_type="select",
                required=True,
                default_value="pymssql",
                options=_options(("pymssql", "pymssql"), ("pyodbc", "pyodbc")),
            ),
            ConnectionFieldDefinition(
                key="odbc_driver",
                label="ODBC Driver",
                advanced=True,
                placeholder="例如：ODBC Driver 18 for SQL Server",
                show_when={"driver_mode": "pyodbc"},
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：TrustServerCertificate=yes",
                description="每行一个 key=value",
            ),
        ]
    elif normalized == "oracle":
        fields = [
            *_base_network_fields(profile),
            ConnectionFieldDefinition(
                key="oracle_target_mode",
                label="连接标识",
                input_type="select",
                required=True,
                default_value="service_name",
                options=_options(("service_name", "Service Name"), ("sid", "SID")),
            ),
            ConnectionFieldDefinition(
                key="service_name",
                label="Service Name",
                required=True,
                placeholder="例如：orclpdb1",
                show_when={"oracle_target_mode": "service_name"},
            ),
            ConnectionFieldDefinition(
                key="sid",
                label="SID",
                required=True,
                placeholder="例如：orcl",
                show_when={"oracle_target_mode": "sid"},
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：encoding=UTF-8",
            ),
        ]
    elif normalized == "dm":
        fields = [
            *_base_network_fields(profile),
            ConnectionFieldDefinition(
                key="database",
                label="数据库名",
                placeholder="例如：dmdb",
            ),
            ConnectionFieldDefinition(
                key="dm_connection_mode",
                label="连接方式",
                input_type="select",
                required=True,
                default_value="odbc_driver",
                options=_options(("odbc_driver", "ODBC Driver"), ("dsn", "DSN")),
            ),
            ConnectionFieldDefinition(
                key="odbc_driver",
                label="ODBC Driver",
                required=True,
                placeholder="例如：DM8 ODBC DRIVER",
                show_when={"dm_connection_mode": "odbc_driver"},
            ),
            ConnectionFieldDefinition(
                key="dsn",
                label="DSN",
                placeholder="例如：DM8_TEST",
                show_when={"dm_connection_mode": "dsn"},
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：schema=SYSDBA",
            ),
        ]
    elif normalized == "sqlite":
        fields = [
            ConnectionFieldDefinition(
                key="file_path",
                label="SQLite 文件路径",
                required=True,
                placeholder="例如：C:/data/demo.sqlite",
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：mode=ro",
            ),
        ]
    elif normalized == "clickhouse":
        fields = [
            *_base_network_fields(profile),
            ConnectionFieldDefinition(
                key="database",
                label="数据库名",
                default_value="default",
                placeholder="例如：default",
            ),
            ConnectionFieldDefinition(
                key="interface",
                label="连接协议",
                input_type="select",
                default_value="http",
                options=_options(("http", "HTTP"), ("native", "Native")),
            ),
            ConnectionFieldDefinition(
                key="extra_params",
                label="高级参数",
                input_type="textarea",
                advanced=True,
                placeholder="例如：compression=lz4",
            ),
        ]
    else:
        raise ValueError(f"Unsupported database type: {normalized}")

    defaults = {
        field.key: field.default_value
        for field in fields
        if field.default_value not in (None, "")
    }

    return {
        "db_type": normalized,
        "display_name": profile["display_name"],
        "default_port": profile.get("default_port"),
        "supports_advanced_mode": True,
        "fields": [field.to_dict() for field in fields],
        "defaults": defaults,
    }


def build_connection_url(db_type: str, form: dict[str, Any]) -> str:
    """根据结构化表单生成标准连接 URL。"""

    normalized = normalize_database_type(db_type)
    extra = _parse_extra_params(form.get("extra_params"))

    if normalized in {"mysql", "oceanbase", "tidb", "polardb", "goldendb"}:
        return _build_network_url(
            scheme=normalized,
            host=_clean_string(form.get("host")),
            port=_clean_int(
                form.get("port"),
                get_database_profile(normalized)["default_port"],
            ),
            username=_clean_optional_string(form.get("username")),
            password=_clean_optional_string(form.get("password")),
            path=_clean_string(form.get("database")),
            query=extra,
        )

    if normalized in {"postgresql", "kingbase", "gaussdb", "vastbase", "highgo"}:
        return _build_network_url(
            scheme=normalized,
            host=_clean_string(form.get("host")),
            port=_clean_int(
                form.get("port"),
                get_database_profile(normalized)["default_port"],
            ),
            username=_clean_optional_string(form.get("username")),
            password=_clean_optional_string(form.get("password")),
            path=_clean_string(form.get("database")),
            query=extra,
        )

    if normalized == "sqlserver":
        driver_mode = _clean_string(form.get("driver_mode")) or "pymssql"
        if driver_mode == "pyodbc" and _clean_string(form.get("odbc_driver")):
            extra["odbc_driver"] = _clean_string(form.get("odbc_driver"))
        return _build_network_url(
            scheme=normalized,
            host=_clean_string(form.get("host")),
            port=_clean_int(
                form.get("port"),
                get_database_profile(normalized)["default_port"],
            ),
            username=_clean_optional_string(form.get("username")),
            password=_clean_optional_string(form.get("password")),
            path=_clean_string(form.get("database")),
            query=extra,
        )

    if normalized == "oracle":
        target_mode = _clean_string(form.get("oracle_target_mode")) or "service_name"
        if target_mode == "sid":
            extra["sid"] = _clean_string(form.get("sid"))
        else:
            extra["service_name"] = _clean_string(form.get("service_name"))
        return _build_network_url(
            scheme=normalized,
            host=_clean_string(form.get("host")),
            port=_clean_int(
                form.get("port"),
                get_database_profile(normalized)["default_port"],
            ),
            username=_clean_optional_string(form.get("username")),
            password=_clean_optional_string(form.get("password")),
            path="",
            query=extra,
        )

    if normalized == "dm":
        connection_mode = _clean_string(form.get("dm_connection_mode")) or "odbc_driver"
        if connection_mode == "dsn":
            extra["dsn"] = _clean_string(form.get("dsn"))
        else:
            extra["odbc_driver"] = _clean_string(form.get("odbc_driver"))
        return _build_network_url(
            scheme=normalized,
            host=_clean_string(form.get("host")),
            port=_clean_int(
                form.get("port"),
                get_database_profile(normalized)["default_port"],
            ),
            username=_clean_optional_string(form.get("username")),
            password=_clean_optional_string(form.get("password")),
            path=_clean_optional_string(form.get("database")),
            query=extra,
        )

    if normalized == "sqlite":
        return _build_sqlite_url(_clean_string(form.get("file_path")), query=extra)

    if normalized == "clickhouse":
        if _clean_string(form.get("interface")):
            extra["interface"] = _clean_string(form.get("interface"))
        return _build_network_url(
            scheme=normalized,
            host=_clean_string(form.get("host")),
            port=_clean_int(
                form.get("port"),
                get_database_profile(normalized)["default_port"],
            ),
            username=_clean_optional_string(form.get("username")),
            password=_clean_optional_string(form.get("password")),
            path=_clean_string(form.get("database")) or "default",
            query=extra,
        )

    raise ValueError(f"Unsupported database type: {normalized}")


def parse_connection_url(db_type: str, url: str) -> dict[str, Any]:
    """把原始 URL 尝试解析回普通模式字段。"""

    normalized = normalize_database_type(db_type)
    parsed = urlsplit(url)
    query = _split_url_query(url)
    warnings: list[str] = []

    if normalized == "sqlite":
        form = {"file_path": unquote(parsed.path.lstrip("/"))}
        extra = dict(query)
    else:
        form = {
            "host": parsed.hostname or "",
            "port": str(
                parsed.port
                or get_database_profile(normalized).get("default_port")
                or ""
            ),
            "username": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
        }
        extra = dict(query)

        if normalized in {
            "mysql",
            "oceanbase",
            "tidb",
            "polardb",
            "goldendb",
            "postgresql",
            "kingbase",
            "gaussdb",
            "vastbase",
            "highgo",
            "sqlserver",
            "clickhouse",
            "dm",
        }:
            form["database"] = _extract_path_value(url)

    if normalized == "oracle":
        if "sid" in extra:
            form["oracle_target_mode"] = "sid"
            form["sid"] = extra.pop("sid")
        else:
            form["oracle_target_mode"] = "service_name"
            form["service_name"] = extra.pop("service_name", "")
    elif normalized == "sqlserver":
        if "odbc_driver" in extra:
            form["driver_mode"] = "pyodbc"
            form["odbc_driver"] = extra.pop("odbc_driver")
        else:
            form["driver_mode"] = "pymssql"
    elif normalized == "clickhouse":
        form["interface"] = extra.pop("interface", "http")
    elif normalized == "dm":
        if "dsn" in extra:
            form["dm_connection_mode"] = "dsn"
            form["dsn"] = extra.pop("dsn")
        else:
            form["dm_connection_mode"] = "odbc_driver"
            form["odbc_driver"] = extra.pop("odbc_driver", "")

    scheme_base = _extract_scheme_base(url)
    if scheme_base != normalized:
        warnings.append(
            f"当前 URL 使用的 scheme 为 {scheme_base}，与当前数据库类型 {normalized} 不一致。"
        )

    form["extra_params"] = (
        "\n".join(f"{key}={value}" for key, value in extra.items()) if extra else ""
    )
    return {
        "db_type": normalized,
        "form": form,
        "warnings": warnings,
        "can_use_form_mode": True,
        "masked_url": mask_connection_url(url),
    }
