"""
Skill Selector - Use LLM to select the most appropriate skill
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SkillSelector:
    """Use LLM to select appropriate skill (JSON mode)"""

    SELECTOR_SYSTEM = """你是一个技能选择系统。在选择技能之前，分析用户的真实意图。

## 关键规则

1. **首先理解任务类型**
   - 这是一个演示文稿/幻灯片？→ 不要选择 poster-design
   - 这是一个文档/报告？→ 不要选择 poster-design
   - 这是一个网页？→ 不要选择 poster-design
   - 这是一个知识库问答/证据检索？→ 考虑 evidence-based-rag

2. **检查负面信号**
   - 如果用户想要"幻灯片"、"演示文稿"、"deck"→ 拒绝 poster-design
   - 如果用户想要"文档"、"报告"→ 拒绝 poster-design
   - 如果用户想要"网页"、"落地页"→ 拒绝 poster-design
   - 如果用户想要"代码"、"脚本"→ 拒绝所有非编码技能

3. **仅在以下情况选择：**
   - 技能的主要目的与任务类型匹配
   - 技能专门为此用例设计
   - 使用该技能将显著提升结果质量

4. **如有疑问，返回 selected: false**
   - 使用通用代理能力比强制使用错误的技能更好

## 错误选择示例

| 用户任务 | 错误技能 | 原因 |
|-----------|-------------|-----|
| "创建一个演示幻灯片" | poster-design | 用户想要幻灯片，不是海报 |
| "写一份营销报告" | poster-design | 用户想要文档，不是视觉设计 |
| "生成 HTML 落地页" | poster-design | 用户想要网页，不是海报 |
| "修复这个 Python bug" | 任何非编码技能 | 任务需要编码，不是其他技能 |

## 决策流程

1. 识别核心输出类型（幻灯片/海报/文档/代码等）
2. 检查是否有技能为此输出类型设计
3. 验证没有冲突信号
4. 然后才选择技能

如果没有技能直接相关，返回 selected: false。"""

    def __init__(self, llm: Any) -> None:
        """
        Args:
            llm: BaseLLM instance
        """
        self.llm = llm

    async def select(self, task: str, candidates: List[Dict]) -> Optional[Dict]:
        """
        Select the most appropriate skill, or return None

        Args:
            task: User task
            candidates: List of candidate skills

        Returns:
            Selected skill, or None
        """
        if not candidates:
            logger.warning("No candidate skills available for selection")
            return None

        logger.info(f"Selecting skill for task: {task[:100]}...")
        logger.info(f"Available candidates: {len(candidates)} skills")

        prompt = self._build_prompt(task, candidates)

        logger.info("Calling LLM for skill selection...")

        # First try JSON mode, fall back to normal mode if not supported
        try:
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.SELECTOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.warning(f"JSON mode not supported, falling back to normal mode: {e}")
            response = await self.llm.chat(
                messages=[
                    {"role": "system", "content": self.SELECTOR_SYSTEM},
                    {"role": "user", "content": prompt},
                ]
            )

        # Handle different return types
        if isinstance(response, str):
            content = response
        elif isinstance(response, dict):
            # Handle dictionary format response (e.g., OpenAI format)
            if "content" in response:
                content = response["content"]
            else:
                content = str(response)
        elif hasattr(response, "content"):
            content = response.content
        else:
            content = str(response)

        logger.info(f"LLM response received: {len(content)} chars")
        logger.debug(f"Raw response: {content[:500]}...")

        # Try to parse JSON
        try:
            result = json.loads(content)
        except json.JSONDecodeError as e:
            # Try to extract JSON from markdown
            logger.warning(
                f"Response is not valid JSON: {e}, trying to extract from markdown"
            )
            content = content.strip()
            # Remove markdown code block markers
            if content.startswith("```"):
                # Find the first newline
                newline_idx = content.find("\n")
                if newline_idx > 0:
                    content = content[newline_idx:].strip()
                # Remove trailing ```
                if content.endswith("```"):
                    content = content[:-3].strip()

            logger.debug(f"Extracted content: {content[:500]}...")

            try:
                result = json.loads(content)
            except json.JSONDecodeError as e2:
                logger.error(f"Failed to parse JSON after markdown extraction: {e2}")
                logger.error(f"Content was: {content}")
                return None

        if not result.get("selected"):
            reasoning = result.get("reasoning", "No reasoning provided")
            logger.info(f"No skill selected. Reasoning: {reasoning}")
            return None

        skill_name = result.get("skill_name")
        reasoning = result.get("reasoning", "No reasoning provided")

        # Find the selected skill
        selected_skill = next((s for s in candidates if s["name"] == skill_name), None)

        if selected_skill:
            logger.info(f"✓ Skill selected: '{skill_name}'")
            logger.info(
                f"  Description: {selected_skill.get('description', 'N/A')[:100]}..."
            )
            logger.info(f"  Reasoning: {reasoning}")
        else:
            logger.error(
                f"LLM selected skill '{skill_name}' but it was not found in candidates!"
            )

        return selected_skill

    def _build_prompt(self, task: str, candidates: List[Dict]) -> str:
        """Build selection prompt"""
        skills_desc = []

        for i, skill in enumerate(candidates):
            desc = f"""{i + 1}. **{skill["name"]}**
   Description: {skill.get("description", "N/A")}
   When to use: {skill.get("when_to_use", "N/A")}
   Tags: {", ".join(skill.get("tags", []))}"""
            skills_desc.append(desc)

        # Extract key signal words from task
        task_lower = task.lower()
        signal_words = {
            "slide": "slide" in task_lower or "presentation" in task_lower,
            "poster": "poster" in task_lower or "banner" in task_lower,
            "document": "document" in task_lower or "report" in task_lower,
            "web": "web" in task_lower
            or "landing" in task_lower
            or "html page" in task_lower,
            "code": "code" in task_lower
            or "script" in task_lower
            or "fix bug" in task_lower,
            "knowledge_base_qa": "knowledge base" in task_lower
            or "evidence" in task_lower
            or "verification" in task_lower
            or "due diligence" in task_lower
            or "retrieval" in task_lower,
        }

        detected_types = [k for k, v in signal_words.items() if v]

        return f"""## 用户任务
{task}

## 检测到的任务类型
{", ".join(detected_types) if detected_types else "通用任务（未检测到特定类型）"}

## 可用技能
{chr(10).join(skills_desc)}

## 重要提示
- 分析真实意图，而不仅仅是关键词匹配
- 考虑用户想要的输出类型
- 选择前检查负面信号

返回 JSON 格式：
{{"selected": true/false, "skill_name": "选择的技能名称（或 null）", "reasoning": "简要解释为什么此技能适合（或不适合）任务类型"}}"""
