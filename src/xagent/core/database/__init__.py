"""Unified database type definitions and helpers."""

from .connection_form import (
    build_connection_url,
    get_connection_form_definition,
    mask_connection_url,
    parse_connection_url,
)
from .profiles import DATABASE_PROFILES, get_database_profile, list_database_profiles
from .types import (
    DATABASE_TYPE_ALIASES,
    DATABASE_TYPE_CANONICAL_VALUES,
    DatabaseType,
    normalize_database_type,
)

__all__ = [
    "DATABASE_TYPE_ALIASES",
    "DATABASE_TYPE_CANONICAL_VALUES",
    "DATABASE_PROFILES",
    "DatabaseType",
    "build_connection_url",
    "get_database_profile",
    "get_connection_form_definition",
    "list_database_profiles",
    "mask_connection_url",
    "normalize_database_type",
    "parse_connection_url",
]
