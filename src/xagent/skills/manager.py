"""
技能管理器 - 管理技能扫描与检索
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .parser import SkillParser
from .selector import SkillSelector

logger = logging.getLogger(__name__)


class SkillManager:
    """技能系统的核心管理器"""

    def __init__(self, skills_roots: List[Path]):
        """
        参数:
            skills_roots: 技能目录路径列表（支持多个目录）
                - 第一个是内置技能目录（只读）
                - 后续是用户自定义技能目录（可写）
        """
        self.skills_roots = [Path(p) for p in skills_roots]

        self._skills_cache: Dict[str, Dict] = {}
        self._initialized = False
        self._init_task: Optional[Any] = None

    async def ensure_initialized(self) -> None:
        """确保初始化完成（惰性加载模式）"""
        if self._initialized:
            return

        # If there's an initialization task running, wait for it to complete
        if self._init_task is not None:
            await self._init_task
            return

        # Create and execute initialization task
        self._init_task = asyncio.create_task(self._do_initialize())
        await self._init_task

    async def _do_initialize(self) -> None:
        """实际初始化逻辑"""
        await self.initialize()
        self._init_task = None

    async def initialize(self) -> None:
        """初始化：扫描所有技能"""
        logger.info("📂 Scanning skills...")
        for root in self.skills_roots:
            logger.info(f"  from {root}...")
        await self.reload()
        self._initialized = True
        logger.info(f"✓ Loaded {len(self._skills_cache)} skills")

    async def reload(self) -> None:
        """重新加载所有技能"""
        self._skills_cache.clear()

        # Scan all directories in order (later ones override earlier ones)
        for skills_root in self.skills_roots:
            if not skills_root.is_dir():
                # Skip non-existent directories silently
                continue

            logger.debug(f"Scanning directory: {skills_root}")
            found_count = 0

            for skill_dir in skills_root.iterdir():
                if not skill_dir.is_dir():
                    continue

                if not (skill_dir / "SKILL.md").exists():
                    logger.warning("Skipping %r: no SKILL.md found", skill_dir)
                    continue

                try:
                    skill_info = SkillParser.parse(skill_dir)
                    self._skills_cache[skill_info["name"]] = skill_info
                    # Determine source by checking if it's the builtin directory
                    source = (
                        "builtin"
                        if skills_root == self.get_builtin_root()
                        else skills_root.name
                    )
                    logger.info(f"  ✓ Loaded: {skill_info['name']} ({source})")
                    found_count += 1
                except Exception as e:
                    logger.error(
                        f"  ✗ Error loading {skill_dir.name}: {e}", exc_info=True
                    )

            logger.debug(f"Found {found_count} skills in {skills_root}")

        logger.info(f"Total skills loaded: {len(self._skills_cache)}")

    async def select_skill(
        self,
        task: str,
        llm: Any,
        tracer: Optional[Any] = None,
        task_id: Optional[str] = None,
        allowed_skills: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        根据任务选择合适的技能

        参数:
            task: 用户任务
            llm: 用于技能选择的 LLM 实例
            tracer: 用于发送追踪事件的追踪器实例（可选）
            task_id: 追踪事件的任务 ID（可选）
            allowed_skills: 可选的可选技能列表，用于过滤

        返回:
            选中的技能，或 None
        """
        await self.ensure_initialized()

        if not self._skills_cache:
            logger.debug("No skills available for selection")
            return None

        # Filter by allowed_skills if specified
        candidates = list(self._skills_cache.values())
        if allowed_skills is not None:
            allowed_set = set(allowed_skills)
            candidates = [s for s in candidates if s["name"] in allowed_set]
            logger.info(
                f"Filtered to {len(candidates)} allowed skills: {allowed_skills}"
            )

        if not candidates:
            logger.debug("No skills available after filtering")
            return None

        logger.debug(f"Selecting skill for task: {task[:100]}...")
        logger.debug(f"Available skills: {len(candidates)}")

        # Send skill selection start event if tracer is provided
        if tracer and task_id:
            from xagent.core.agent.trace import (
                trace_skill_select_end,
                trace_skill_select_start,
            )

            await trace_skill_select_start(
                tracer,
                task_id,
                data={
                    "task": task[:200],  # Limit task length
                    "available_skills_count": len(candidates),
                    "allowed_skills": allowed_skills,
                },
            )

        selector = SkillSelector(llm)

        try:
            selected_skill = await selector.select(task=task, candidates=candidates)

            # Send skill selection end event if tracer is provided
            if tracer and task_id:
                from xagent.core.agent.trace import trace_skill_select_end

                await trace_skill_select_end(
                    tracer,
                    task_id,
                    data={
                        "task": task[:200],
                        "selected": selected_skill is not None,
                        "skill_name": selected_skill.get("name")
                        if selected_skill
                        else None,
                    },
                )

            return selected_skill
        except Exception as e:
            # Send skill selection error event if tracer is provided
            if tracer and task_id:
                from xagent.core.agent.trace import trace_error

                await trace_error(
                    tracer,
                    task_id=task_id,
                    error_type="SkillSelectionError",
                    error_message=str(e),
                )
            raise

    async def list_skills(self) -> List[Dict]:
        """列出所有技能（简要信息）"""
        await self.ensure_initialized()
        return [
            {
                "name": skill["name"],
                "description": skill.get("description", ""),
                "when_to_use": skill.get("when_to_use", ""),
                "tags": skill.get("tags", []),
            }
            for skill in self._skills_cache.values()
        ]

    async def get_skill(self, name: str) -> Optional[Dict]:
        """获取单个技能（包含模板的完整信息）"""
        await self.ensure_initialized()
        return self._skills_cache.get(name)

    def has_skills(self) -> bool:
        """检查是否有可用技能"""
        return len(self._skills_cache) > 0

    @classmethod
    def get_builtin_root(cls) -> Path:
        """获取内置技能目录"""
        return Path(__file__).parent / "builtin"
