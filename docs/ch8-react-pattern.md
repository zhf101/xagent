# ReAct 模式

ReAct（Reasoning and Acting，推理与行动）模式是 xagent 的主要执行循环——通过结构化推理、工具调用和观察的迭代周期驱动自主任务完成的认知引擎。本文剖析该模式的架构、执行语义和集成点，使其成为独立智能体运行和 [DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)工作流中子智能体执行的骨干。

## 架构定位

ReAct 位于 `core.agent.pattern` 包中，是抽象 [`AgentPattern`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/base.py#L9-L29) 接口的两个具体实现之一。与 DAG 模式预先将任务分解为可并行执行的计划不同，ReAct 通过单线程决策循环运作，LLM 在每一步推理下一步该做什么。

**源码参考：** [base.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/base.py#L9-L29)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L57-L164)

## 结构化动作模型

与解析自由格式 "Thought/Action/Observation" 文本块的经典 ReAct 公式不同，xagent 强制执行**结构化 JSON 动作契约**。LLM 必须在每次响应中返回 [`Action`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L66-L91) Pydantic 模型，完全消除模糊的文本解析。

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `type` | `str` | `"tool_call"` 或 `"final_answer"`——动作区分符 |
| `reasoning` | `str` | 所选动作的思维链论证 |
| `tool_name` | `Optional[str]` | 目标工具标识符（`type="tool_call"` 时必需） |
| `tool_args` | `Optional[Dict]` | 工具调用参数 |
| `answer` | `Optional[str]` | 最终响应内容（`type="final_answer"` 时必需） |
| `success` | `Optional[bool]` | 任务完成状态标志，默认 `True` |
| `error` | `Optional[str]` | `success=False` 时的错误描述 |
| `code` | `Optional[str]` | 编程任务的代码内容 |
| _(extra)_ | `Any` | 通过 `Config.extra = "allow"` 允许额外字段 |

这种双模式设计意味着 LLM 可以要么调用工具收集信息，要么直接提供带有 `success` 布尔值的最终答案——启用循环可以检测和处理的显式失败信号。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L66-L91)

## 执行流程

核心执行遵循由 [`_execute_react_loop()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L646-L845) 管理的紧密推理-行动-观察循环。两个公共入口点——独立执行的 [`run()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L515-L644) 和子智能体调用的 [`run_with_context()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L852-L1022)——在设置各自的消息上下文后都委托给这个共享方法。

### 迭代生命周期

循环内的每次迭代遵循精确序列。首先，系统通过 `asyncio.Event` 对象检查暂停和中断信号——这些通过 [`pause_execution()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L500-L504)、[`resume_execution()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L505-L509) 和 [`interrupt_execution()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L510-L514) 支持长时间运行的任务控制。然后调用 `_get_action_from_llm()` 处理上下文压缩、消息清理和带有 JSON 响应格式强制的流式 LLM 调用。响应要么是原生工具调用（通过 [`_convert_native_tool_call_to_action()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1590-L1611) 转换），要么是由 `json_repair` 库修复的 JSON 字符串。结果 `Action` 传递给 `_execute_action()` 根据动作类型分发。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L646-L845)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L500-L514)

## 独立执行 vs 子智能体执行

模式支持两种不同的调用模式，各有不同的初始化语义和追踪行为。

### 独立模式：`run()`

[`run()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L515-L644) 方法是顶级智能体执行的主入口点。它接受任务字符串、内存存储、工具列表和可选的 `AgentContext`。内部，它创建任务 ID 和虚拟步骤上下文，用 `ToolRegistry` 注册所有工具，用从内存存储检索的相关记忆增强任务，构建系统提示，并委托给共享循环。成功完成后，它发射任务级追踪事件（`trace_task_completion`、`trace_task_end`）。

### 子智能体模式：`run_with_context()`

[`run_with_context()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L852-L1022) 方法设计用于 DAG 步骤内调用——当图节点将执行委托给 ReAct 驱动的智能体时。它要求预先调用 `set_step_context()` 以提供父级的任务和步骤 ID。它不构建新消息列表，而是接收预构建消息（通常包含步骤的任务描述和先前上下文），通过 [`_build_enhanced_system_prompt()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1121-L1228) 将 Action 格式要求合并到任何现有系统提示中，并运行共享循环。关键是，`is_sub_agent` 标志抑制任务级完成事件，防止 DAG 子步骤错误地向前端发出整体任务完成信号。

| 方面 | `run()` | `run_with_context()` |
| --- | --- | --- |
| **步骤上下文** | 自动创建虚拟步骤 | 需要先调用 `set_step_context()` |
| **消息构建** | 新系统 + 用户对 | 合并到现有消息列表 |
| **内存集成** | 追加到任务文本 | 就地注入用户消息 |
| **任务级追踪** | 发射完成事件 | 通过 `is_sub_agent` 标志抑制 |
| **错误处理** | 抛出异常 | 返回 `{"success": False, ...}` 字典 |

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L515-L644)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L852-L1022)

## 系统提示工程

系统提示由 [`_build_system_prompt()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1024-L1119) 基于两个因素动态构建：`AgentContext.state` 中是否存在自定义系统提示，以及是否有注册的工具。当没有工具可用时，提示明确指示 LLM 直接响应 `final_answer`——防止幻觉工具调用。当工具存在时，它列出所有注册的工具名称并提供 tool_call 和 final_answer 的 JSON 示例。

对于子智能体上下文，[`_build_enhanced_system_prompt()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1121-L1228) 将 `=== ACTION FORMAT REQUIREMENTS ===` 块追加到现有系统提示而非替换它，保留父 DAG 步骤注入的任何领域特定指令，同时仍强制结构化动作契约。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1024-L1228)

## LLM 通信和响应解析

[`_get_action_from_llm()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1300-L1520) 方法处理整个 LLM 通信管道，具有多层回退。

### 流式架构

方法使用 `stream_chat()` 而非 `chat()` 增量处理 LLM 响应。流式循环累积 token 增量、收集原生工具调用并跟踪使用统计。这种方法支持可观测性的实时 token 报告，并通过 `is_error()` 块类型检查允许优雅处理流式错误。

### JSON 强制与修复

所有 LLM 调用包含 `response_format: {"type": "json_object"}` 以请求结构化输出。然而，由于并非所有提供商都能可靠遵守此要求，响应管道包含健壮的修复链：

1. **原生工具调用**——如果流式响应包含 `tool_calls` 块，方法完全绕过 JSON 解析并通过 [`_convert_native_tool_call_to_action()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1590-L1611) 将它们转换为 `Action` 对象
2. **JSON 修复**——字符串响应通过 `json_repair` 库（`repair_loads`）处理，可处理截断的 JSON、无效转义和其他常见 LLM 输出格式问题
3. **规范化**——[`_normalize_action_data()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1521-L1568) 处理字段类型强制和结构调整
4. **类型推断**——[`_ensure_action_type()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1570-L1588) 当 `type` 字段缺失时从 `tool_name` vs `answer` 字段的存在推断动作类型

### 思考模式抑制

对于支持扩展思考的提供商（如 Claude），方法显式设置 `thinking: {"type": "disabled"}` 以防止 LLM 进入会破坏结构化动作输出格式的推理模式。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1300-L1520)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1590-L1611)

## 上下文压缩

长时间运行的 ReAct 会话积累的对话历史可能超出上下文窗口限制。模式通过基于 [`CompactConfig`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/utils/compact.py) 和 [`CompactUtils`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/utils/compact.py) 构建的自动上下文压缩系统解决这个问题。

当估计 token 计数超过可配置阈值（默认 12,000 token）时激活压缩管道。[`_compact_react_context()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L226-L340) 方法将整个对话发送给压缩 LLM（默认为主 LLM），附带保留最近工具调用、当前任务上下文和重要推理同时删除冗余系统消息和过时失败尝试的指令。[`_smart_truncate_react_messages()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L341-L370) 方法提供次级回退，策略性地移除较旧的 assistant-observation 对以减少 token 计数同时保持对话连贯性。最后的回退 [`_fallback_truncate_messages()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L421-L443) 在所有压缩策略失败时执行硬截断。

压缩系统通过构造函数参数 `compact_threshold`、`enable_auto_compact` 和 `compact_llm` 可配置，并通过 [`get_compact_stats()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L470-L485) 暴露统计信息。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L164-L213)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L226-L443)

## 内存集成

ReAct 在生命周期的两个点与 xagent 的内存子系统集成：任务开始时的**检索**和任务完成时的**生成**。

### 内存检索

在 `run()` 和 `run_with_context()` 中，模式使用 [`_lookup_relevant_memories_with_context()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L2067-L2083) 从 `MemoryStore` 检索相关记忆。这个包装器确保从 `asyncio.to_thread` 调用内存存储时正确传播用户上下文（因为内存存储内部使用同步 DB 操作）。记忆以 `"react_memory"` 类别存储，并通过 [`enhance_goal_with_memory()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/memory_utils.py#L16-L52) 增强到任务描述中。

### 内存生成

任务完成或失败后，[`_generate_and_store_react_memories()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1802-L1950) 生成包括工具使用模式、推理策略和失败学习的综合洞察。这些通过 [`store_react_task_memory()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/memory_utils.py#L233-L315) 存储，创建带有类别、分类和元数据的结构化记忆笔记，回馈到未来任务检索。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L586-L630)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1802-L1950)，[memory_utils.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/memory_utils.py#L16-L52)

## 工具执行

[`_execute_action()`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1613-L1762) 方法作为动作分发器。对于 `tool_call` 动作，它在 `ToolRegistry` 中查找工具，通过 `tool.run_json_async()` 异步执行，并将结果包装在观察字典中。对于 `final_answer` 动作，它验证 answer 字段并检查 `success` 标志——如果 `success` 为 `False` 则引发 `PatternExecutionError` 触发重试循环。[`ToolRegistry`](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L94-L148) 提供按名称查找工具并为 LLM 工具调用支持生成 OpenAI 风格函数模式。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L94-L148)，[react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L1613-L1762)

## 可观测性与追踪

ReAct 生命周期中的每个重要事件都通过 `Tracer` 系统发射追踪事件，包括任务开始/结束、动作开始/结束、LLM 调用、工具执行、内存检索/存储和错误。每个追踪事件包含当前 `step_id` 和 `step_name`，支持 ReAct 迭代与其父工作流上下文（无论是独立还是 DAG 内）之间的关联。

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L30-L48)

## 配置参考

| 参数 | 类型 | 默认值 | 描述 |
| --- | --- | --- | --- |
| `llm` | `BaseLLM` | _必需_ | 推理用的语言模型 |
| `max_iterations` | `int` | `200` | 最大思考-行动-观察循环次数 |
| `tracer` | `Optional[Tracer]` | `Tracer()` | 事件追踪器实例 |
| `compact_threshold` | `Optional[int]` | `12000` | 上下文压缩的 token 阈值 |
| `enable_auto_compact` | `bool` | `True` | 启用自动上下文压缩 |
| `compact_llm` | `Optional[BaseLLM]` | 与 `llm` 相同 | 压缩用的独立 LLM |
| `memory_store` | `Optional[MemoryStore]` | `None` | 持久化用的内存存储 |
| `is_sub_agent` | `bool` | `False` | 用于 DAG 集成的子智能体模式 |

**源码参考：** [react.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/react.py#L164-L213)

## 下一步

- **[基础智能体模型](https://zread.ai/xorbitsai/xagent/5-base-agent-model)**——`ReActPattern` 如何连接到 `Agent` 类并按智能体配置
- **[DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)**——ReAct 如何通过 `run_with_context()` 作为 DAG 图步骤内的执行引擎
- **[内置核心工具](https://zread.ai/xorbitsai/xagent/12-built-in-core-tools)**——ReAct 智能体在动作循环中可调用的工具
- **[内存存储架构](https://zread.ai/xorbitsai/xagent/17-memory-store-architecture)**——存储和检索 ReAct 执行记忆的持久化层