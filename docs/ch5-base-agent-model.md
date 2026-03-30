# 基础智能体模型

基础智能体模型（Base Agent Model）是 xagent 架构中的核心抽象层——每一个智能操作，从简单的 ReAct 循环到多步骤 DAG 计划，最终都解析为由模式（pattern）、运行器（runner）和服务层协调的 `Agent` 实例。理解这个模型是理解任务如何在系统中流转、嵌套子智能体如何委托工作、以及领域专用垂直智能体如何扩展基础契约的前提。

**源码参考：** [agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L15-L138)，[service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L22-L47)

## 架构概览

智能体系统采用分层架构，每一层都有明确的职责：数据结构持有状态，模式定义行为，运行器协调执行，服务管理生命周期。下图展示了核心组件关系及其继承层次。

**源码参考：** [agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L15-L44)，[vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L22-L81)，[vertical_agent_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L24-L128)

## 智能体核心

`Agent` 类是核心数据结构。它被设计得非常精简——持有配置和状态，但本身不包含执行逻辑。每个智能体由构造时传入的五个核心组件定义：**名称**、定义其推理方式的**模式列表**、用于对话/状态持久化的**内存存储**、用于行动能力的**工具列表**，以及可选的用于语言推理的 **LLM**。

```python
agent = Agent(
    name="researcher",
    patterns=[react_pattern],
    memory=InMemoryMemoryStore(),
    tools=[web_search, file_tool],
    llm=my_llm,
    system_prompt="You are a research assistant...",
)
```

除了配置，`Agent` 还维护支持嵌套子智能体执行的运行时状态。每个智能体跟踪自己的**执行历史**（消息字典列表）、**最终结果**、**步骤 ID**（当智能体作为 DAG 步骤运行时使用）、**创建时间戳**，以及带有双向父引用的**子智能体**字典。`add_sub_agent` 方法自动设置子智能体的 `_parent_agent` 指针，形成树状结构，这对后文描述的 `AgentTool` 包装机制至关重要。

**源码参考：** [agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L20-L44)，[agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L54-L61)

### 智能体序列化

`to_dict` 方法提供了一个轻量级检查 API，返回包含智能体名称、模式类名、工具名称、内存类型、LLM 可用性、子智能体名称、执行历史状态、创建时间戳和步骤 ID 的字典表示。这主要用于调试以及通过追踪系统将智能体元数据传输到前端。

**源码参考：** [agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L125-L137)

## 执行上下文

`AgentContext` 是一个 Pydantic `BaseModel`，作为智能体执行期间的共享可变状态容器。它与智能体自身的属性不同——智能体持有**配置**，而上下文持有作用于单次任务执行的**运行时状态**。

| 字段 | 类型 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `task_id` | `str` | UUID4 | 当前任务的唯一标识符 |
| `user_id` | `Optional[str]` | `None` | 多租户场景的用户关联 |
| `session_id` | `Optional[str]` | `None` | 对话连续性的会话分组 |
| `start_time` | `datetime` | UTC now | 执行开始时间戳 |
| `history` | `list[str]` | `[]` | 执行期间累积的字符串条目 |
| `state` | `dict[str, Any]` | `{}` | 自由格式的键值存储，用于前提条件填充和模式间通信 |

`state` 字典尤为重要：它是 `PreconditionResolver` 在执行开始前进行槽位填充的机制，并且将 `system_prompt` 从智能体传递到运行器的上下文中。

**源码参考：** [context.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/context.py#L8-L18)，[runner.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L27-L29)

## 模式抽象

`AgentPattern` 是定义智能体如何**思考**的抽象基类。每个具体模式必须实现一个异步方法：

```python
class AgentPattern(ABC):
    @abstractmethod
    async def run(
        self,
        task: str,
        memory: MemoryStore,
        tools: list[Tool],
        context: Optional[AgentContext] = None,
    ) -> dict[str, Any]:
        """执行模式。返回至少包含 'success' 布尔值的字典。"""
```

这个契约被刻意简化。无论复杂度如何，模式都接收相同的输入——`ReActPattern` 用它们执行单次迭代思考-行动循环，而 `DAGPlanExecutePattern` 用它们进行规划、执行并行步骤，并在多次迭代中执行目标检查。模式是智能体策略模式设计中的**策略**。

**源码参考：** [base.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/base.py#L9-L29)

## AgentRunner：执行协调器

`AgentRunner` 将 `Agent` 实例与其 `AgentContext` 和可选的 `PreconditionResolver` 桥接起来执行任务。它遵循两阶段执行模型：

**阶段一——前提条件解析**：如果附加了 `PreconditionResolver`，运行器进入循环检查 `context.state` 中是否存在所有必需字段。对于每个缺失的字段，它提示用户并存储响应，直到所有槽位被填充。

**阶段二——模式执行**：运行器按顺序遍历智能体的模式列表。对于每个模式，它调用 `pattern.run()` 并传入任务、内存、工具和上下文。如果模式返回 `need_user_input`，运行器提示额外输入并重新执行该模式。第一个返回 `success: true` 的模式获胜——运行器立即返回该结果。如果所有模式都失败，运行器收集每次尝试的详细错误信息（包括自定义 `AgentException` 类型的完整回溯）并返回合并的失败结果。

错误处理被刻意设计为防御性的：`AgentException` 子类被捕获并保留其结构化上下文，而 `ValueError`、`KeyError` 和 `TypeError` 被归类为数据验证错误，`RuntimeError` 为运行时失败，其他所有异常为意外错误。这确保一个模式的失败不会阻止后续模式的尝试。

**源码参考：** [runner.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L13-L169)，[runner.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L31-L78)

## AgentService：生命周期管理器

`AgentService` 是面向生产的服务层，用工作空间管理、工具初始化、暂停/恢复控制、任务延续、追踪和错误规范化来包装 `Agent`。它是 Web 层执行任务的主要 API 接口。

### 初始化和智能体创建

构造函数接受一套全面的参数，包括多个 LLM 变体（`llm`、`fast_llm`、`vision_llm`、`compact_llm`）、工作空间配置、工具配置和 `agent_type` 字符串。初始化流程如下：

1. 设置内存（默认为 `InMemoryMemoryStore`）、工具和 LLM 实例
2. 配置工作空间（可选择与 tool_config 共享）
3. 如果没有提供工具或 tool_config，创建默认 `ToolConfig`
4. 实例化模式——如果 `use_dag_pattern` 为 true 且有 LLM 可用，创建 `DAGPlanExecutePattern`；否则创建 `ReActPattern`；如果没有 LLM 可用，模式保持为空
5. 通过 `VerticalAgentFactory.create_agent()` 创建实际的 `Agent` 实例，传入 `agent_type` 参数

这个工厂委托是关键扩展点：`agent_type` 字符串决定实例化标准 `Agent` 还是领域专用的 `VerticalAgent`。

**源码参考：** [service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L25-L223)

### 任务执行流程

`execute_task` 是主入口点。它执行惰性工具初始化，验证模式存在，处理任务延续（现有任务的后续消息），并规范化结果格式。对于 DAG 模式，返回的结果包含详细的 `dag_status` 及执行阶段信息；对于非 DAG 模式，返回更简单的元数据字典。所有结果遵循一致的结构：`{"status", "output", "success", "metadata"}`。

**源码参考：** [service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L230-L380)

### 多 LLM 配置

服务支持分层 LLM 架构，不同模型处理不同工作负载：

| LLM 参数 | 角色 | 使用者 |
| --- | --- | --- |
| `llm` | 主推理模型 | DAG 规划、ReAct 循环、工具调用 |
| `fast_llm` | 简单任务的轻量模型 | DAG 步骤执行（子智能体创建） |
| `compact_llm` | 上下文压缩模型 | ReAct 上下文压缩、DAG 步骤压缩 |
| `vision_llm` | 图像理解模型 | 视觉工具处理 |

当同时提供 `fast_llm` 和 `llm` 时，DAG 模式使用双 LLM 配置，主 LLM 处理复杂规划，快速 LLM 执行单个步骤——降低简单子任务的成本和延迟。

**源码参考：** [service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L39-L46)，[service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L142-L161)

## 通过 AgentTool 实现嵌套智能体执行

`AgentTool` 类桥接智能体层次结构和工具系统。它将任何 `Agent` 实例包装为 `Tool`，使父智能体能够通过标准工具调用机制将专门子任务委托给子智能体。这就是 DAG 步骤智能体的创建方式——DAG 计划中的每个步骤由轻量级智能体执行，该智能体作为工具被协调 DAG 模式调用。

`AgentTool` 通过 `CompactMode` 枚举支持两种上下文处理模式：

| 模式 | 行为 |
| --- | --- |
| `COMPACT` | 返回仅包含输出和成功状态的压缩结果，最小化父智能体中的上下文污染 |
| `FULL` | 返回完整执行结果，包括历史、迭代和所有元数据 |

该工具还提供 `query_agent_details` 方法，使用被包装智能体的 LLM 回答关于其执行历史的自然语言问题——使父智能体能够内省子智能体行为。

**源码参考：** [agent_tool.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/tools/agent_tool.py#L20-L219)

## VerticalAgent：领域扩展点

`VerticalAgent` 用领域专用行为的抽象契约扩展基础 `Agent`。与接受预构建工具和模式不同，`VerticalAgent` 通过子类必须实现的三个抽象方法**生成**它们：

- **`_get_domain_tools()`** — 返回该领域的默认工具集
- **`_get_domain_patterns()`** — 返回该领域的默认执行模式
- **`_get_domain_prompt()`** — 返回领域专用的系统提示

初始化时，如果工具、模式或系统提示没有显式提供，垂直智能体会自动使用这些方法填充它们。这种控制反转意味着创建新的领域智能体只需实现三个方法并在工厂中注册。

`VerticalAgent` 还为专门行为提供生命周期钩子：`get_step_trace_data` 和 `get_completion_trace_data` 允许领域智能体将结构化数据注入追踪系统，`_post_process_result` 和 `_handle_domain_error` 提供领域专用的结果处理和错误处理。

**源码参考：** [vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L22-L123)，[vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L199-L306)

## VerticalAgentFactory：注册与创建

`VerticalAgentFactory` 实现类级注册表模式。新的垂直智能体通过 `register_vertical_agent(name, agent_class)` 按名称注册，存储在类级字典中。调用 `create_agent` 时，工厂首先检查注册表——如果 `agent_type` 匹配已注册的垂直智能体，则实例化该类。对于 `"standard"`、`"agent"` 或 `"default"` 类型，创建基础 `Agent`。未知类型引发 `ValueError` 并列出可用类型。

工厂通过 `_ensure_initialized()` 使用惰性初始化，首次访问时调用 `_register_default_agents()`。默认情况下没有预注册的垂直智能体——注册表设计为在导入时由外部模块（如 `src/xagent/core/agents/vertical/` 包）填充。

**源码参考：** [vertical_agent_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L24-L144)

## 异常层次结构

智能体系统使用以 `AgentException` 为根的结构化异常层次结构。每个异常携带可选的 `context`（相关状态的字典）、`cause`（原始异常）和 `to_dict()` 方法用于序列化。层次结构按失败领域组织：

| 异常类 | 领域 | 关键属性 |
| --- | --- | --- |
| `AgentConfigurationError` | 配置 | — |
| `LLMNotAvailableError` | LLM | — |
| `LLMResponseError` | LLM | `response`, `expected_format` |
| `ToolNotFoundError` | 工具 | `tool_name`, `available_tools` |
| `ToolExecutionError` | 工具 | `tool_name`, `tool_args` |
| `PatternExecutionError` | 模式 | `pattern_name`, `iteration` |
| `MaxIterationsError` | 模式 | `pattern_name`, `max_iterations` |
| `ReActParsingError` | ReAct | `response`, `expected_format` |
| `DAGPlanGenerationError` | DAG | `iteration`, `llm_response` |
| `DAGStepError` | DAG | `step_id`, `step_name`, `dependencies` |
| `DAGDependencyError` | DAG | `step_id`, `invalid_dependencies` |
| `DAGDeadlockError` | DAG | `pending_steps`, `blocked_dependencies` |
| `ContextCompactionError` | 上下文 | `original_size`, `target_step` |
| `AgentToolError` | 嵌套智能体 | `agent_name`, `sub_agent_error` |

提供工厂函数 `create_execution_error` 用于将遗留的基于字符串的错误处理转换为类型化层次结构。

**源码参考：** [exceptions.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/exceptions.py#L1-L425)

## 追踪集成

`Tracer` 类提供分层事件系统，用于实时观察智能体执行。事件沿三个轴分类——**范围**（TASK, STEP, ACTION, SYSTEM）、**动作**（START, END, UPDATE, ERROR, INFO）和**类别**（DAG, REACT, LLM, TOOL, MEMORY 等）。`Tracer` 将事件分发给注册的处理程序，有两个内置实现：`ConsoleTraceHandler` 用于开发日志，`DatabaseTraceHandler` 用于持久存储。

便捷函数覆盖每个重要的生命周期事件：`trace_task_start/end`、`trace_step_start/end`、`trace_action_start/end`、`trace_llm_call_start`、`trace_tool_execution_start`、`trace_memory_*` 事件，以及专门函数如 `trace_dag_plan_start`、`trace_compact_start` 和 `trace_visualization_update`。`AgentService` 将其追踪器实例传递给所有模式和智能体，创建从服务初始化到单个工具调用的统一可观测性流。

**源码参考：** [trace.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/trace.py#L13-L59)，[trace.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/trace.py#L313-L333)

## 组件关系总结

| 组件 | 角色 | 实例化者 | 关键依赖 |
| --- | --- | --- | --- |
| `Agent` | 状态 + 配置持有者 | `VerticalAgentFactory` | Patterns, Memory, Tools, LLM |
| `AgentContext` | 运行时执行状态 | `AgentRunner` | `AgentContext`（Pydantic 模型） |
| `AgentPattern` | 执行策略（抽象） | `AgentService` 或 `VerticalAgent` | `BaseLLM`, `Tracer` |
| `AgentRunner` | 任务执行协调器 | `Agent.get_runner()` | `Agent`, `AgentContext`, `PreconditionResolver` |
| `AgentService` | 生产生命周期管理器 | Web 层 / API 路由 | `Agent`, `Tracer`, `TaskWorkspace` |
| `AgentTool` | 智能体即工具适配器 | `DAGPlanExecutePattern` | `Agent` 实例 |
| `VerticalAgent` | 领域专用智能体（抽象） | `VerticalAgentFactory` | 抽象方法实现 |
| `VerticalAgentFactory` | 智能体创建注册表 | `AgentService` | 已注册的垂直智能体类 |
| `Tracer` | 事件发射系统 | `AgentService` | `TraceHandler` 实现 |

---

接下来推荐阅读：

- **[智能体运行器执行](https://zread.ai/xorbitsai/xagent/6-agent-runner-execution)** — 深入了解 `AgentRunner` 如何协调两阶段执行流程和处理模式回退
- **[ReAct 模式](https://zread.ai/xorbitsai/xagent/8-react-pattern)** — 详细审视思考-行动-观察循环和上下文压缩
- **[DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)** — DAG 模式如何规划、执行并行步骤和检查目标完成
- **[垂直智能体框架](https://zread.ai/xorbitsai/xagent/7-vertical-agent-framework)** — 如何使用 `VerticalAgent` 扩展点创建领域专用智能体