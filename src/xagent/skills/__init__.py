"""
xagent Skills Module

This module provides a skill management system compatible with Claude Skills format.
Skills are directory-based modules that provide knowledge and templates for task planning.
"""

from .manager import SkillManager
from .parser import SkillParser
from .selector import SkillSelector
from .availability import SkillAvailabilityService
from .catalog import SkillCatalogService
from .catalog_models import (
    SkillAvailability,
    SkillContextSummary,
    SkillDescriptor,
    SkillMetadata,
)
from .context import SkillContextAssembler

__all__ = [
    "SkillAvailability",
    "SkillAvailabilityService",
    "SkillCatalogService",
    "SkillContextAssembler",
    "SkillContextSummary",
    "SkillDescriptor",
    "SkillManager",
    "SkillMetadata",
    "SkillParser",
    "SkillSelector",
]
