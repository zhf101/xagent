# XAgent Memory Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 xagent 的记忆系统从“单一 `MemoryNote` 混合存储”升级为“分层记忆 + 统一命名 + 可闭环检索”的可扩展架构。

**Architecture:** 以现有 `MemoryStore` / `LanceDBMemoryStore` 为底座，新增结构化记忆字段 `memory_type` / `memory_subtype` / `scope`，先统一 React 与 DAG 的经验记忆读写闭环，再逐步补充 `session_summary`、异步提炼与治理能力。短期保持向后兼容，允许旧 `category` 继续读取；中期由结构化字段替代执行路径命名。

**Tech Stack:** Python, Pydantic, FastAPI, LanceDB, pytest

---

## 1. 设计目标

- 统一命名，避免 `react_memory`、`execution_memory`、`dag_plan_execute_memory` 继续扩散。
- 区分不同用途的记忆，避免会话连续性、长期事实、执行经验、RAG 知识混在一起。
- 修复当前 DAG 记忆“写了但下一次规划读不到”的闭环问题。
- 保持向后兼容，不一次性打碎现有 API 和存储格式。

## 2. 统一命名

### 2.1 `memory_type`（记忆主类型）

- `transcript`：原始会话消息、工具调用、执行轨迹
- `session_summary`：会话摘要，用于上下文压缩和恢复
- `durable`：长期稳定记忆，例如用户偏好、项目约束
- `experience`：执行经验，例如成功模式、失败案例、工具使用经验
- `knowledge`：知识库 / RAG 文档片段

### 2.2 `memory_subtype`（记忆子类型）

- `user_profile`：用户画像
- `user_preference`：用户偏好
- `project_context`：项目背景
- `project_constraint`：项目约束
- `working_style`：协作或编码风格
- `reference_fact`：长期参考事实
- `task_outcome`：任务结果
- `execution_pattern`：执行模式或可复用策略
- `failure_case`：失败案例
- `tool_usage`：工具使用经验
- `decision_log`：关键决策
- `document_chunk`：文档切片

### 2.3 `scope`（记忆作用域）

- `user`：用户级
- `project`：项目级
- `task`：任务级
- `team`：团队级
- `global`：全局级

## 3. 分层架构

### 3.1 `Transcript Memory`（原始会话记忆）

- 保存原始输入、输出、工具轨迹
- 用于审计、恢复、重放
- 不直接作为长期记忆注入 prompt

### 3.2 `Session Summary Memory`（会话摘要记忆）

- 按 session 维护一份摘要
- 解决长会话中的“刚才聊到哪了”
- 注入 prompt 时优先级最高，但只保留 1 条

### 3.3 `Durable Memory`（长期稳定记忆）

- 保存跨会话仍然有价值的事实
- 例如：用户偏好、项目约束、长期约定

### 3.4 `Experience Memory`（执行经验记忆）

- 保存“以前怎么做过、什么策略有效、踩过哪些坑”
- React 与 DAG 统一使用这一层

### 3.5 `Knowledge Memory`（知识库记忆）

- 保持现有 RAG / 文档检索体系
- 不与 agent 自身经验记忆混淆

## 4. 第一阶段实施范围

第一阶段只做最值钱的两件事：

1. 引入结构化记忆字段，保持向后兼容
2. 统一 React / DAG 的 `experience` 记忆读写闭环

不在第一阶段做的内容：

- 不新增 session summary
- 不做异步 durable memory 提炼
- 不改前端展示
- 不重构所有 memory API

## 5. 文件拆分任务

### Task 1: Add Memory Schema

**Files:**
- Create: `src/xagent/core/memory/schema.py`
- Modify: `src/xagent/core/memory/core.py`
- Modify: `src/xagent/core/memory/base.py`
- Modify: `src/xagent/core/memory/__init__.py`
- Test: `tests/core/memory/test_in_memory.py`

- [ ] 定义 `MemoryType`、`MemorySubtype`、`MemoryScope`
- [ ] 定义旧 `category` 到新结构化字段的兼容映射
- [ ] 在 `MemoryNote` 增加 `memory_type`、`memory_subtype`、`scope`、`importance`、`confidence`、`freshness_at` 等字段
- [ ] 保证旧数据只带 `category` 也能正常读取

### Task 2: Upgrade Store Filtering

**Files:**
- Modify: `src/xagent/core/memory/in_memory.py`
- Modify: `src/xagent/core/memory/lancedb.py`
- Modify: `src/xagent/web/user_isolated_memory.py`
- Test: `tests/core/memory/test_in_memory.py`
- Test: `tests/core/memory/test_lancedb.py`

- [ ] 让存储层支持按 `memory_type`、`memory_subtype`、`scope` 过滤
- [ ] 兼容旧 `category` 查询
- [ ] 确保用户隔离逻辑不被新字段破坏

### Task 3: Fix Experience Memory Loop

**Files:**
- Modify: `src/xagent/core/agent/pattern/memory_utils.py`
- Modify: `src/xagent/core/agent/pattern/react.py`
- Modify: `src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py`
- Test: `tests/core/agent/pattern/test_memory_utils.py`

- [ ] React 检索统一读 `memory_type=experience`
- [ ] React 写入统一写 `memory_type=experience`
- [ ] DAG 规划检索统一读 `memory_type=experience`
- [ ] DAG 执行结果统一写 `memory_type=experience`
- [ ] 让增强后的记忆文本带上基本来源信息，便于调试

### Task 4: Verification

**Files:**
- Test: `tests/core/agent/pattern/test_memory_utils.py`
- Test: `tests/core/memory/test_in_memory.py`
- Test: `tests/core/memory/test_lancedb.py`

- [ ] 覆盖旧 `category` 到新 `memory_type` 的兼容推断
- [ ] 覆盖 `experience` 记忆写入与检索闭环
- [ ] 覆盖存储层 `memory_type` / `memory_subtype` 过滤

## 6. 后续阶段

### Phase 2: Layered Retrieval

- 新增 `MemoryQuery`
- 新增 `MemoryRetriever`
- Prompt 按 `session_context` / `durable_memories` / `past_experiences` / `knowledge_refs` 分块注入

### Phase 3: Session Summary

- 新增 `session_summary` 层
- 按 session 增量维护摘要

### Phase 4: Async Extraction and Governance

- 后台提炼 durable / experience
- 做 dedupe、stale 标记、过期治理

## 9. 当前实施进度

### 已完成

- `Task 1: Add Memory Schema`
- `Task 2: Upgrade Store Filtering`
- `Task 3: Fix Experience Memory Loop`
- `Phase 2: Layered Retrieval`
- `Phase 3: Session Summary`
- `Phase 4 / Wave 1: memory_jobs + repository + manager`
- `Phase 4 / Wave 2: extract executor + worker + React/DAG enqueue`
- `Phase 4 / Wave 3: consolidate executor + expire executor + maintenance scheduler`

### 当前系统行为

- React / DAG 执行结束后，不再同步提炼 durable / experience
- 主流程只负责必要的即时记忆写入，然后异步 enqueue memory governance job
- 独立 worker 从数据库 claim job，再执行提炼 / 合并 / 过期治理
- `expired` 记忆不会继续被 `MemoryRetriever` 召回

### 当前还没做

- 记忆治理任务的前端可视化与管理界面
- dead / failed memory job 的手动重试入口
- 可配置化的治理策略中心
- 更复杂的批量治理、分布式调度、heartbeat 续租

## 7. 实施顺序

1. Task 1: Add Memory Schema
2. Task 2: Upgrade Store Filtering
3. Task 3: Fix Experience Memory Loop
4. Task 4: Verification

## 8. 验收标准

- `MemoryNote` 支持结构化字段，同时兼容旧 `category`
- React 与 DAG 统一使用 `experience` 记忆层
- DAG 执行后写入的经验，下一次规划可以检索到
- InMemory / LanceDB 都支持按 `memory_type` 过滤
