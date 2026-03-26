"""Unified database type definitions and helpers."""

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
    "get_database_profile",
    "list_database_profiles",
    "normalize_database_type",
]
