"""
Skill utilities - Utility functions for creating skill_manager
"""

import logging
from pathlib import Path
from typing import List, Optional

from ..config import get_external_skills_dirs
from ..core.storage.manager import get_storage_root
from .manager import SkillManager

logger = logging.getLogger(__name__)


def create_skill_manager(
    skills_roots: Optional[List[Path]] = None,
) -> "SkillManager":
    """
    Create skill_manager (not initialized)

    Args:
        skills_roots: Optional list of skills directories. If None, uses defaults:
                     - builtin, project (./skills/), user (~/.xagent/skills/)
                     - XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS env var is always appended if set, regardless of this parameter.

    Returns:
        SkillManager instance (not initialized)
    """

    if skills_roots is None:
        # Start with default directories if not specified
        skills_roots = _get_default_skill_dirs()

    # Always append external directories from environment variable
    external_dirs = get_external_skills_dirs()
    if external_dirs:
        skills_roots = skills_roots + external_dirs
        logger.info(f"Appended {len(external_dirs)} external skill directories")

    # Import here to avoid circular import
    from .manager import SkillManager

    # Create skill_manager (not initialized)
    skill_manager = SkillManager(skills_roots=skills_roots)

    return skill_manager


def _get_default_skill_dirs() -> List[Path]:
    """
    Get default skill directories.

    Load order (later skills override earlier ones with the same name):
    1. Built-in skills (read-only, shipped with xagent)
    2. Project skills (./skills/ in current working directory)
    3. User skills (~/.xagent/skills/, created if needed)

    Returns:
        List of default skill directory paths
    """
    builtin_skills_dir = SkillManager.get_builtin_root()
    project_skills_dir = Path("skills")
    user_skills_dir = get_storage_root() / "skills"

    return [builtin_skills_dir, project_skills_dir, user_skills_dir]
