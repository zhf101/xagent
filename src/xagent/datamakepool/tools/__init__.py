"""Datamakepool specialist tool sets with lazy imports."""

from __future__ import annotations

from typing import Any


def create_sql_tools(*args: Any, **kwargs: Any):
    from .sql_tools import create_sql_tools as _impl

    return _impl(*args, **kwargs)


def create_http_tools(*args: Any, **kwargs: Any):
    from .http_tools import create_http_tools as _impl

    return _impl(*args, **kwargs)


def create_dubbo_tools(*args: Any, **kwargs: Any):
    from .dubbo_tools import create_dubbo_tools as _impl

    return _impl(*args, **kwargs)


def create_mcp_tools(*args: Any, **kwargs: Any):
    from .mcp_tools import create_mcp_tools as _impl

    return _impl(*args, **kwargs)


async def create_legacy_scenario_meta_tools(*args: Any, **kwargs: Any):
    from .legacy_scenario_meta_tools import create_legacy_scenario_meta_tools as _impl

    return await _impl(*args, **kwargs)


__all__ = [
    "create_sql_tools",
    "create_http_tools",
    "create_dubbo_tools",
    "create_mcp_tools",
    "create_legacy_scenario_meta_tools",
]
