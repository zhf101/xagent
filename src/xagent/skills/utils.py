"""
技能工厂辅助函数。

当前保留两类工厂：
- `create_skill_manager()`：兼容旧调用点
- `create_skill_catalog_service()`：面向新产品化目录能力
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

from .catalog import SkillCatalogService
from .manager import SkillManager

logger = logging.getLogger(__name__)


def create_skill_manager(skills_roots: Optional[List[Path]] = None) -> SkillManager:
    """
    Create skill_manager (not initialized)

    Args:
        skills_roots: Optional list of skills directories, defaults to:
                     1. Built-in and user directories (always included)
                     2. XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS env var (appended if set)

    Returns:
        SkillManager instance (not initialized)
    """

    if skills_roots is None:
        # Always start with default directories
        skills_roots = _get_default_skill_dirs()

        # Append external directories if configured
        env_dirs = os.getenv("XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS", "")
        if env_dirs:
            external_dirs = _parse_skill_dirs(env_dirs)
            if external_dirs:
                skills_roots = skills_roots + external_dirs
                logger.info(
                    f"Appended {len(external_dirs)} external skill directories to defaults"
                )

    # Create skill_manager (not initialized)
    skill_manager = SkillManager(skills_roots=skills_roots)

    return skill_manager


def create_skill_catalog_service(
    skills_roots: Optional[List[Path]] = None,
) -> SkillCatalogService:
    """
    创建技能目录服务。

    设计意图：
    - 旧代码继续使用 `SkillManager`
    - 新代码逐步切到 `SkillCatalogService`
    - 避免在首版产品化改造里一次性替换所有调用点
    """

    return SkillCatalogService(
        skill_manager=create_skill_manager(skills_roots=skills_roots)
    )


def _parse_skill_dirs(env_value: str) -> List[Path]:
    """
    Parse XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS environment variable

    Args:
        env_value: Comma-separated directory paths

    Returns:
        List of valid Path objects
    """
    skills_roots = []

    for dir_path in env_value.split(","):
        dir_path = dir_path.strip()
        if not dir_path:
            continue

        # Check for URL-like paths before path expansion
        if "://" in dir_path:
            logger.warning(f"Skipping non-local path (not supported yet): {dir_path}")
            continue

        # Expand environment variables and user home directory
        expanded_path = os.path.expandvars(dir_path)
        path = Path(expanded_path).expanduser()

        # Validate and add path
        if path.exists():
            if path.is_dir():
                skills_roots.append(path)
                logger.info(f"Added skills directory: {path}")
            else:
                logger.warning(f"Path is not a directory: {path}")
        else:
            logger.warning(f"Skills directory does not exist: {path}")

    return skills_roots


def _get_default_skill_dirs() -> List[Path]:
    """
    Get default skill directories

    Returns:
        List of default skill directory paths
    """
    builtin_skills_dir = Path(__file__).parent / "builtin"
    user_skills_dir = Path(".xagent/skills")
    user_skills_dir.mkdir(parents=True, exist_ok=True)

    return [builtin_skills_dir, user_skills_dir]
