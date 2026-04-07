"""
记忆模块在 Agent Pattern 层的胶水代码。

这个文件不直接存储向量，也不直接暴露 Web API，
它的职责是把「ReAct / DAG 执行流程」和「底层记忆系统」连接起来。

可以把它理解成三类工具：
1. 查询类：从 memory store 里拿到可用上下文。
2. 落库类：把执行结果整理成 MemoryNote 后写入记忆库。
3. 调度类：把较重的记忆提取工作丢到后台 job 队列，避免阻塞主任务。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ...memory import MemoryJobManager, MemoryStore
from ...memory.core import MemoryNote
from ...memory.prompt_builder import enhance_goal_with_memory_bundle
from ...memory.retriever import MemoryBundle, MemoryQuery, MemoryRetriever
from ...memory.schema import (
    MemorySubtype,
    MemoryType,
    default_category_for_type,
)

logger = logging.getLogger(__name__)


def _coerce_optional_int(value: Any) -> Optional[int]:
    """把可能来自 Web 层/上下文层的用户 ID 统一转换成 int。"""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def enqueue_memory_extraction_job(
    *,
    task: str,
    result: Any,
    classification: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[Any] = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    pattern: Optional[str] = None,
    job_manager: Optional[MemoryJobManager] = None,
) -> Optional[int]:
    """
    把“从一次任务结果里提取结构化记忆”的工作放入后台队列。

    这里故意不在主执行链里直接做复杂提取，
    因为提取通常需要额外分析结果、生成候选记忆、做去重，属于耗时操作。
    主任务只负责“尽量成功返回给用户”，后台慢慢补齐长期记忆。

    返回 job id；如果入队失败，返回 None，但不会让主任务失败。
    """
    try:
        manager = job_manager or MemoryJobManager()
        return manager.enqueue_extract_memories(
            task=task,
            result=result,
            classification=classification or {},
            session_id=session_id,
            user_id=_coerce_optional_int(user_id),
            project_id=project_id,
            task_id=task_id,
            pattern=pattern,
        )
    except Exception as exc:
        logger.warning("Failed to enqueue memory extraction job: %s", exc)
        return None


def enhance_goal_with_memory(goal: str, memories: List[Dict[str, Any]]) -> str:
    """
    Enhance goal description with relevant memories using simple natural text.

    Args:
        goal: Original goal description
        memories: List of relevant memories

    Returns:
        Enhanced goal description
    """
    if not memories:
        logger.info("No memories found, returning original goal")
        return goal

    logger.info(f"Enhancing goal with {len(memories)} memories")

    # 这里保持“人类可读”的文本拼接风格，而不是把记忆对象原样塞给模型，
    # 这样对提示词调试更直观，也方便直接打印查看。
    context_parts = []

    for mem in memories:
        content = mem.get("content", "")
        memory_type = mem.get("memory_type")
        memory_subtype = mem.get("memory_subtype")
        if content.strip():
            label_parts = [part for part in [memory_type, memory_subtype] if part]
            prefix = f"[{'/'.join(label_parts)}] " if label_parts else ""
            context_parts.append(f"• {prefix}{content}")

    if context_parts:
        context_text = "\n".join(context_parts)
        enhanced_goal = (
            f"{goal}\n\nRelevant Context from Previous Experience:\n{context_text}"
        )
        logger.info(f"Goal enhanced with {len(context_parts)} insights")
        return enhanced_goal
    else:
        return goal


def enhance_goal_with_bundle(goal: str, bundle: MemoryBundle) -> str:
    """
    使用结构化 MemoryBundle 增强任务描述。

    和上面的 `enhance_goal_with_memory()` 不同，
    这里会保留 session summary / durable / experience 等分区，
    适合已经切换到新版结构化检索的执行链。
    """
    return enhance_goal_with_memory_bundle(goal, bundle)


def store_plan_generation_memory(
    memory_store: MemoryStore,
    goal: str,
    steps_count: int,
    plan_id: Optional[str] = None,
    planning_insights: Optional[str] = None,
    classification: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    把“规划阶段”沉淀成一条经验记忆。

    Args:
        memory_store: Memory store instance
        goal: The goal that was planned
        steps_count: Number of steps generated
        plan_id: Optional plan identifier
        planning_insights: Insights and strategies learned during planning
        classification: Classification data from comprehensive insights

    Returns:
        Memory ID if successful, None otherwise
    """
    try:
        # classification 是上层 LLM 生成的附加洞察。
        # 如果没有，就退化为最小可用记录，避免因为洞察缺失而完全丢失经验。
        if classification:
            domain_keywords = classification.get("keywords", [])
            task_type = classification.get("task_type", "unknown")
        else:
            domain_keywords = []
            task_type = "unknown"

        content = f"Task Planning Experience: {goal}\n\n"
        content += (
            f"Planning Strategy: Generated execution plan with {steps_count} steps"
        )
        if planning_insights:
            content += f"\n\nKey Insights:\n{planning_insights}"

        note = MemoryNote(
            content=content,
            keywords=["task planning", "strategy design", "step decomposition"]
            + domain_keywords,
            # 新版实现里，真正的主分类落在 memory_type / memory_subtype；
            # category 主要保留给旧接口和旧过滤逻辑做兼容。
            category=default_category_for_type(MemoryType.EXPERIENCE.value),
            memory_type=MemoryType.EXPERIENCE.value,
            memory_subtype=MemorySubtype.EXECUTION_PATTERN.value,
            metadata={
                "operation": "dag_plan_generation",
                "goal_type": task_type,
                "steps_count": steps_count,
                "plan_id": plan_id,
                "domain_keywords": domain_keywords,
                "timestamp": datetime.now().isoformat(),
            },
        )

        response = memory_store.add(note)
        logger.info(f"Stored planning memory for goal: {goal[:50]}...")
        return response.memory_id if response.success else None
    except Exception as e:
        logger.error(f"Failed to store plan generation memory: {e}")
        return None


def store_execution_result_memory(
    memory_store: MemoryStore,
    results: List[Any],
    goal: str,
    plan_id: Optional[str] = None,
    execution_insights: Optional[str] = None,
    failures_and_learnings: Optional[str] = None,
    classification: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    把 DAG 执行结果整理成“可复用经验”。

    这里存的不是完整 transcript，而是更偏“经验萃取”的结果，
    方便后续任务检索到“做这类事时成功/失败过什么”。

    Args:
        memory_store: Memory store instance
        results: Execution results
        goal: Original goal for context
        plan_id: Optional plan identifier
        execution_insights: Insights learned during execution
        failures_and_learnings: Failure analysis and lessons learned
        classification: Classification data from comprehensive insights

    Returns:
        Memory ID if successful, None otherwise
    """
    try:
        # 先把执行结果压成几个核心指标，后面写入 metadata 方便过滤与分析。
        successful_steps = len([r for r in results if r.get("status") == "completed"])
        failed_steps = len([r for r in results if r.get("status") == "failed"])

        content_parts = []
        content_parts.append(f"Goal: {goal}")
        content_parts.append(
            f"Execution result: {successful_steps} successful steps out of {len(results)} total steps"
        )

        if classification and classification.get("user_preferences"):
            content_parts.append(
                f"User preferences identified: {classification['user_preferences']}"
            )

        if classification and classification.get("behavioral_patterns"):
            content_parts.append(
                f"User behavior patterns: {classification['behavioral_patterns']}"
            )

        if execution_insights and execution_insights.strip():
            content_parts.append(f"Key execution insights: {execution_insights}")

        if classification and classification.get("success_factors"):
            content_parts.append(
                f"Success factors: {classification['success_factors']}"
            )

        if classification and classification.get("learned_patterns"):
            content_parts.append(
                f"Reusable patterns: {classification['learned_patterns']}"
            )

        if failed_steps > 0:
            if failures_and_learnings and failures_and_learnings.strip():
                content_parts.append(f"Failure analysis: {failures_and_learnings}")
            if classification and classification.get("improvement_suggestions"):
                content_parts.append(
                    f"Improvement suggestions: {classification['improvement_suggestions']}"
                )

        if classification:
            extra_insights = []
            if classification.get("execution_insights"):
                extra_insights.append(
                    f"Execution approach: {classification['execution_insights']}"
                )
            if classification.get("failure_analysis"):
                extra_insights.append(
                    f"Failure analysis: {classification['failure_analysis']}"
                )

            if extra_insights:
                content_parts.append("Additional insights:")
                content_parts.extend(f"  - {insight}" for insight in extra_insights)

        # content 依然保持自然语言，原因是：
        # 1. 后续 LLM 检索时更容易理解；
        # 2. 人工排查时不需要先读复杂 JSON。
        content = "\n".join(content_parts)
        keywords = ["execution", "planning"]

        note = MemoryNote(
            content=content,
            keywords=keywords,
            category=default_category_for_type(MemoryType.EXPERIENCE.value),
            memory_type=MemoryType.EXPERIENCE.value,
            memory_subtype=(
                MemorySubtype.FAILURE_CASE.value
                if failed_steps > 0
                else MemorySubtype.TASK_OUTCOME.value
            ),
            metadata={
                "successful_steps": successful_steps,
                "failed_steps": failed_steps,
                "total_steps": len(results),
                "has_user_preferences": bool(
                    classification and classification.get("user_preferences")
                ),
                "timestamp": datetime.now().isoformat(),
            },
        )

        response = memory_store.add(note)
        logger.info(f"Stored execution memory with user preferences: {goal[:50]}...")
        return response.memory_id if response.success else None
    except Exception as e:
        logger.error(f"Failed to store execution result memory: {e}")
        return None


def store_react_task_memory(
    memory_store: MemoryStore,
    task: str,
    result: Dict[str, Any],
    tool_usage_insights: Optional[str] = None,
    reasoning_strategy: Optional[str] = None,
    classification: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    把单次 ReAct 执行沉淀成任务结果记忆。

    这条记忆比 DAG 的执行记忆更轻量，重点记录：
    - 任务是否成功
    - 有没有明显用户偏好
    - 有没有值得复用/规避的模式

    Args:
        memory_store: Memory store instance
        task: The task that was executed
        result: Task execution result
        tool_usage_insights: Insights about tool usage effectiveness
        reasoning_strategy: Strategy used for reasoning and problem solving
        classification: Classification data (will be converted to natural text)

    Returns:
        Memory ID if successful, None otherwise
    """
    try:
        success = result.get("success", False)

        # 这里刻意只保留高价值字段，避免把每次普通执行都写成冗长噪音。
        content_parts = []
        content_parts.append(f"Task: {task}")
        content_parts.append(f"Outcome: {'Success' if success else 'Failed'}")

        if classification:
            if classification.get("user_preferences"):
                content_parts.append(f"User: {classification['user_preferences']}")
            if classification.get("core_insight"):
                content_parts.append(f"Core: {classification['core_insight']}")
            if classification.get("failure_patterns"):
                content_parts.append(f"Failure: {classification['failure_patterns']}")
            if classification.get("success_patterns"):
                content_parts.append(f"Success: {classification['success_patterns']}")

        if tool_usage_insights and len(tool_usage_insights.strip()) > 20:
            content_parts.append(f"Tools: {tool_usage_insights}")

        content = "\n".join(content_parts)
        keywords = ["react", "execution"]

        note = MemoryNote(
            content=content,
            keywords=keywords,
            category=default_category_for_type(MemoryType.EXPERIENCE.value),
            memory_type=MemoryType.EXPERIENCE.value,
            memory_subtype=MemorySubtype.TASK_OUTCOME.value,
            metadata={
                "task": task,
                "success": success,
                "tool_usage": bool(tool_usage_insights),
                "timestamp": datetime.now().isoformat(),
            },
        )

        response = memory_store.add(note)
        logger.info(f"Stored ReAct memory: {task[:50]}...")
        return response.memory_id if response.success else None
    except Exception as e:
        logger.error(f"Failed to store ReAct task memory: {e}")
        return None


def lookup_relevant_memories(
    memory_store: MemoryStore,
    query: str,
    category: Optional[str] = None,
    include_general: bool = True,
    limit: int = 5,
    similarity_threshold: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    使用旧式“扁平结果”方式查询记忆。

    这个函数还保留着，是为了兼容项目里老的调用点；
    新链路更推荐使用下面的 `lookup_memory_bundle()`，
    因为它能区分 session summary / durable / experience 等不同语义层。

    Args:
        memory_store: Memory store instance
        query: Search query
        category: Optional memory category filter (system memory category)
        include_general: Whether to also include general (user) memories
        limit: Maximum number of results
        similarity_threshold: Optional similarity threshold for vector search (0.1-2.0)

    Returns:
        List of relevant memories
    """
    try:
        all_memories = []
        search_filters: list[dict[str, Any]] = []

        if category:
            # 迁移后的查询优先使用 memory_type，而不是旧的 category。
            # 这样 durable/experience/knowledge 的语义更稳定。
            search_filters.append({"memory_type": category})

        if include_general:
            search_filters.append({"category": "general"})

        logger.info(
            f"Looking up memories for query: '{query[:100]}...' with filters: {search_filters}"
        )

        for filter_item in search_filters:
            category_memories = memory_store.search(
                query=query,
                k=limit,
                filters=filter_item,
                similarity_threshold=similarity_threshold,
            )
            all_memories.extend(category_memories)
            logger.info(
                f"Found {len(category_memories)} memories using filters {filter_item}"
            )

        # 不同过滤器可能会查到同一条记忆，这里做一次内容去重。
        seen_contents = set()
        unique_memories = []
        for memory in all_memories:
            content = memory.content
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            if content not in seen_contents:
                seen_contents.add(content)
                unique_memories.append(memory)

        final_memories = unique_memories[:limit]

        logger.info(
            f"Returning {len(final_memories)} unique memories (removed {len(all_memories) - len(final_memories)} duplicates)"
        )

        for i, memory in enumerate(final_memories):
            category_name = getattr(memory, "category", "unknown")
            logger.info(f"Memory {i + 1}: [{category_name}] {memory.content[:100]!r}...")

        return [
            {
                "content": memory.content,
                "keywords": memory.keywords,
                "memory_type": getattr(memory, "memory_type", None),
                "memory_subtype": getattr(memory, "memory_subtype", None),
                "metadata": memory.metadata,
            }
            for memory in final_memories
        ]
    except Exception as e:
        logger.error(
            f"Failed to lookup relevant memories for query '{query[:50]}...': {e}"
        )
        return []


def lookup_memory_bundle(
    memory_store: MemoryStore,
    query: str,
    category: Optional[str] = None,
    include_general: bool = True,
    limit: int = 5,
    similarity_threshold: Optional[float] = None,
    session_id: Optional[str] = None,
) -> MemoryBundle:
    """
    用新版结构化方式查询记忆。

    `category` 还保留着，主要是为了兼容旧调用方传参；
    但真正起主导作用的是 MemoryQuery 里的分项开关和 limit。

    返回值是 MemoryBundle，可以把它理解成“分区后的上下文包”：
    - session_context：本会话摘要
    - durable_memories：长期稳定事实
    - past_experiences：历史经验
    - knowledge_refs：知识库引用
    """
    retriever = MemoryRetriever(memory_store)
    memory_query = MemoryQuery(
        query=query,
        session_id=session_id,
        include_session_summary=bool(session_id),
        durable_limit=2 if include_general else 0,
        experience_limit=limit if category == MemoryType.EXPERIENCE.value else 0,
        similarity_threshold=similarity_threshold,
        include_durable=include_general,
    )
    return retriever.retrieve(memory_query)


# Simple usage examples:
#
# In DAG plan generation:
# memories = lookup_relevant_memories(memory_store, goal, "dag_plan_execute_memory")
# enhanced_goal = enhance_goal_with_memory(goal, memories)
# # Use enhanced_goal for planning
# store_plan_generation_memory(memory_store, goal, len(plan.steps))
#
# In ReAct pattern:
# memories = lookup_relevant_memories(memory_store, task, "react_memory")
# enhanced_task = enhance_goal_with_memory(task, memories)
# # Use enhanced_task for execution
# store_react_task_memory(memory_store, task, result)
