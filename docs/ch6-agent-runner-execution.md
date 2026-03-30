# 智能体运行器执行

**智能体运行器执行**系统是 XAgent 的运行核心——将声明式智能体定义转换为实时、可观察的任务执行的机制。本文深入剖析双层执行架构，追踪从服务初始化到模式调度、错误恢复和状态重建的完整生命周期。如果你是从[基础智能体模型](https://zread.ai/xorbitsai/xagent/5-base-agent-model)过来的，这里就是智能体静态配置变成动态行为的地方。

## 架构概览：双层执行模型

XAgent 将执行关注点分离到两个互补层。**AgentService** 作为应用级协调器——管理生命周期、工作空间、工具初始化、追踪、暂停/恢复语义和任务延续。**AgentRunner** 是底层的模式调度器——负责前提条件解析和具有容错能力的顺序模式执行。这种分离确保可观测性和持久化等横切关注点永远不会泄漏到核心执行循环中。

## AgentRunner：模式调度引擎

[runner.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py) 中的 `AgentRunner` 类是一个专注的单一职责组件。其构造函数接受一个 `Agent` 实例和可选的 `PreconditionResolver`，然后为每次执行创建新的 `AgentContext`。智能体的系统提示（如果存在）在构造时注入到上下文的 state 字典中（[runner.py#L20-L29](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L20-L29)）。

`run(task)` 方法实现两阶段协议：

**阶段一——前提条件解析**：如果提供了 `PreconditionResolver`，运行器进入循环调用 `resolver.resolve(context)` 检查缺失的必需字段。解析器遍历 `required_fields` 列表，为第一个缺失值返回包含字段名和问题的提示字典（[precondition.py#L15-L26](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/precondition.py#L15-L26)）。运行器收集用户输入并存储到 `context.state`，直到所有前提条件满足。这是面向同步 CLI 的机制——在 Web 层，`AgentService` 用 WebSocket 介导的输入处理替换它。

**阶段二——模式回退链**：运行器按顺序遍历智能体的 `patterns` 列表。每个模式的 `run()` 方法接收任务字符串、内存存储、工具列表和共享上下文（[runner.py#L56-L61](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L56-L61)）。`AgentPattern` 抽象基础契约很简单——单个异步方法返回至少包含 `success` 布尔值的 `dict`（[base.py#L15-L28](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/base.py#L15-L28)）。如果模式返回 `need_user_input`，运行器提示缺失字段并重新调用同一模式（[runner.py#L64-L73](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L64-L73)）。第一次成功结果时，运行器立即返回——不尝试后续模式。

### 异常处理策略

运行器采用分层异常捕获策略，在保留最大诊断信息的同时不中断回退链。区分四种异常类别，每类都丰富上下文元数据：

| 异常类别 | 捕获类型 | 捕获的元数据 | 行为 |
| --- | --- | --- | --- |
| **领域异常** | `AgentException` | `context`, `cause`, `to_dict()`, 完整链式回溯 | 用 exc_info 记录，追加到 errors |
| **验证错误** | `ValueError`, `KeyError`, `TypeError` | `exception_type`, `category` 标签 | 记录，追加到 errors |
| **运行时错误** | `RuntimeError` | `exception_type`, `category` 标签 | 记录，追加到 errors |
| **意外错误** | 通用 `Exception` | `exception_type`, `category` 标签 | 记录，追加到 errors——永不重新抛出 |

关键点，运行器永不在回退循环中重新抛出异常（[runner.py#L141-L154](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L141-L154)）。如果所有模式都失败，它返回包含每个 `pattern_errors` 条目、尝试的模式计数和摘要消息的结构化错误字典（[runner.py#L164-L169](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L164-L169)）。`_get_full_traceback` 辅助函数递归跟踪 `__cause__` 链以捕获完整异常谱系，这对 `AgentToolError` 场景特别有价值，其中深层嵌套的子智能体失败需要被呈现（[runner.py#L171-L190](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L171-L190)）。

## AgentService：协调层

[service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py) 中的 `AgentService` 是任务执行的主要公共 API。它包装 `Agent` 实例（通过 `VerticalAgentFactory` 创建）并添加生命周期管理、工作空间隔离、工具生命周期钩子、追踪、暂停/恢复控制和任务延续能力。构造函数接受丰富的参数集——从多个 LLM 槽位到工具配置对象——并将它们连接成一个连贯的执行环境（[service.py#L25-L47](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L25-L47)）。

### 初始化和组件连接

服务构造函数遵循确定的初始化序列：

1. **内存和工具**直接赋值，内存默认为 `InMemoryMemoryStore`（[service.py#L71-L72](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L71-L72)）。
2. **工作空间**从 `tool_config` 的工作空间配置、显式提供的工作空间或通过 `create_workspace()` 惰性创建中解析（[service.py#L98-L122](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L98-L122)）。
3. **模式选择**基于 LLM 可用性和 `use_dag_pattern` 标志发生。有 LLM 且启用 DAG 时，创建 `DAGPlanExecutePattern` 并可访问 `fast_llm`（双 LLM 配置）和 `compact_llm`。无 DAG 时，创建 `ReActPattern`。无 LLM 时，智能体接收空模式列表且无法执行任务（[service.py#L129-L180](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L129-L180)）。
4. **智能体创建**委托给 `VerticalAgentFactory.create_agent()`，传入组装好的配置包括 `agent_type` 参数（[service.py#L200-L222](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L200-L222)）。
5. **追踪器注入**追溯地将服务的 `Tracer` 赋值给任何暴露 `tracer` 属性的模式（[service.py#L226-L228](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L226-L228)）。

### 任务执行流程

`execute_task()` 方法是主要公共入口点。其逻辑根据是否提供 `task_id` 分支，启用任务延续语义（[service.py#L230-L432](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L230-L432)）：

`_execute_normal_task()` 方法是服务实际实现执行的地方（[service.py#L616-L678](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L616-L678)）。它执行五个关键操作：（1）惰性初始化工具，（2）通过 `agent.get_runner()` 创建运行器并将可选上下文应用到运行器的上下文状态，（3）存储或生成 `task_id` 用于延续跟踪，（4）对实现 `setup()` 的每个工具调用它，（5）在 `try/finally` 块中调用 `runner.run(task)`，确保即使失败也调用 `teardown()`。

### 结果规范化

DAG 和标准执行路径都返回具有一致模式的规范化结果字典：

| 字段 | 类型 | 描述 |
| --- | --- | --- |
| `status` | `str` | `"completed"`、`"failed"` 或 `"error"` |
| `output` | `str` | 主要输出或错误消息 |
| `success` | `bool` | 执行是否成功 |
| `error` | `str?` | 错误消息（失败时） |
| `error_details` | `dict?` | `AgentException` 子类型的结构化错误元数据 |
| `dag_status` | `dict?` | DAG 执行阶段和进度（仅 DAG 模式） |
| `metadata` | `dict` | 智能体名称、使用的模式、工具计数、执行类型 |

对于 `AgentException` 失败，`error_details` 丰富异常特定字段：`DAGStepError` 的 `step_id`/`step_name`，`DAGExecutionError` 的 `failed_steps_count`/`completed_steps_count`/`primary_error`（[service.py#L389-L418](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L389-L418)）。

## 暂停、恢复和 WebSocket 输入

服务提供基于 `asyncio.Event` 的协作式暂停/恢复语义。调用 `pause_execution()` 设置 `_is_paused = True` 并传播暂停到所有实现 `pause_execution()` 的模式（[service.py#L434-L457](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L434-L457)）。`resume_execution()` 方法清除标志并设置 `asyncio.Event` 以解除任何等待的协程阻塞（[service.py#L459-L484](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L459-L484)）。

执行期间的 WebSocket 输入通过 `handle_websocket_input()` 处理，它委托给 DAG 模式的 `set_new_user_input()` 方法。这是运行器基于 CLI 的前提条件解析的 Web 层模拟——允许交互式的执行中反馈而不阻塞事件循环（[service.py#L490-L508](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L490-L508)）。

## 从历史重建状态

执行系统的一个独特能力是从历史追踪事件重建活动智能体。`reconstruct_from_history()` 方法接受 `task_id`、`tracer_events` 列表和可选 `plan_state` 字典（[service.py#L749-L762](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L749-L762)）。当 `plan_state` 可用时，它委托给 `_reconstruct_dag_pattern()` 来恢复 DAG 模式的计划、标记已完成步骤并设置执行阶段。无计划状态时，DAG 模式重置到 `PLANNING` 阶段（[service.py#L789-L867](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L789-L867)）。然后从追踪事件重建上下文，允许智能体从中断处恢复（[service.py#L869-L893](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L869-L893)）。这个机制支撑了 Web 应用在页面刷新或服务器重启后重新连接长时间运行的智能体会话的能力。

## 通过 AgentTool 实现嵌套智能体执行

`AgentTool` 类通过将任何 `Agent` 实例包装为可调用 `Tool` 来桥接执行层，使父智能体能够将子任务委托给专门的子智能体。调用时，`AgentTool._execute_agent()` 从被包装的智能体获取运行器，执行它，并通过可配置的压缩模式处理结果（[agent_tool.py#L111-L165](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/tools/agent_tool.py#L111-L165)）。在 `CompactMode.COMPACT` 模式（默认）下，执行历史和中间细节被剥离，只返回最终输出。在 `FULL` 模式下，包括消息和工具调用的完整结果被传回。嵌套执行失败引发 `AgentToolError`，子智能体错误作为原因附加（[agent_tool.py#L39-L215](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/tools/agent_tool.py#L39-L215)）。

伴随的 `QueryStepTool` 提供 DAG 特定的机制，让步骤智能体查询其依赖步骤的执行详情，实现跨步骤推理而不造成原始上下文泛滥（[agent_tool.py#L222-L288](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/tools/agent_tool.py#L222-L288)）。

## 关键类及其职责

| 类 | 文件 | 职责 |
| --- | --- | --- |
| `AgentRunner` | [runner.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py) | 前提条件解析 + 模式回退调度 |
| `AgentService` | [service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py) | 生命周期、工作空间、追踪、暂停/恢复、延续 |
| `Agent` | [agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py) | 数据模型：模式、内存、工具、子智能体、历史 |
| `AgentContext` | [context.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/context.py) | 共享执行状态：`task_id`、`history`、`state` 字典 |
| `PreconditionResolver` | [precondition.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/precondition.py) | 必需上下文字段的槽位填充 |
| `AgentPattern` | [base.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/base.py) | 所有执行策略的抽象 `run()` 契约 |
| `AgentTool` | [agent_tool.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/tools/agent_tool.py) | 用于嵌套执行的智能体即工具适配器 |
| `Tracer` | [trace.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/trace.py) | 多范围事件追踪（task → step → action） |

## 下一步

理解运行器的模式调度自然会引导探索模式本身：基础的 [ReAct 模式](https://zread.ai/xorbitsai/xagent/8-react-pattern)和作为默认执行策略的更复杂的 [DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)。对于流经运行器的上下文管理，参见[内存存储架构](https://zread.ai/xorbitsai/xagent/17-memory-store-architecture)。要理解 `VerticalAgentFactory` 如何创建运行器消费的智能体实例，请参阅[垂直智能体框架](https://zread.ai/xorbitsai/xagent/7-vertical-agent-framework)。