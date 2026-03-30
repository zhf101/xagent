# DAG 计划-执行循环

DAG 计划-执行模式是 XAgent 用于超出单次执行能力的复杂多步骤任务的主要协调策略。与在紧密顺序循环中推理和行动的更简单 [ReAct 模式](https://zread.ai/xorbitsai/xagent/8-react-pattern)不同，此模式将高级目标分解为相互依赖步骤的有向无环图（DAG），尽可能并发执行，并迭代优化计划直到目标满足。它位于智能体执行层核心，桥接[基础智能体模型](https://zread.ai/xorbitsai/xagent/5-base-agent-model)和[基于图的工作流](https://zread.ai/xorbitsai/xagent/10-graph-model-and-nodes)系统。

## 架构概览

模式结构化为三阶段迭代循环——**计划 → 执行 → 检查**——由实现 `AgentPattern` 抽象接口的 `DAGPlanExecutePattern` 类协调。每阶段委托给具有清晰关注点分离的专用组件。

### 模块分解

实现位于 `src/xagent/core/agent/pattern/dag_plan_execute/`，分为六个文件，每个封装单一职责：

| 模块 | 类 | 职责 |
| --- | --- | --- |
| `dag_plan_execute.py` | `DAGPlanExecutePattern` | 顶级协调器；拥有迭代循环、暂停/恢复/中断生命周期和最终结果编译 |
| `plan_generator.py` | `PlanGenerator` | LLM 驱动的计划生成和计划扩展；构建提示、调用 LLM、解析和验证结构化响应 |
| `plan_executor.py` | `PlanExecutor` | 信号量限制并发的队列驱动并发步骤执行、依赖解析和死锁检测 |
| `result_analyzer.py` | `ResultAnalyzer` | 目标达成评估、最终答案生成和通过 LLM 提取内存洞察 |
| `step_agent_factory.py` | `StepAgentFactory` | 创建带基于难度 LLM 选择的每步骤 ReAct 智能体 |
| `models.py` | `PlanStep`, `ExecutionPlan`, `StepStatus`, `ExecutionPhase`, `StepInjection`, `UserInputMapper` | 计划结构、步骤生命周期、条件分支和用户输入到步骤映射的不可变数据模型 |

**源码参考：** [dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L1-L10)，[models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L1-L10)，[base.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/base.py#L9-L29)

## 迭代计划-执行-检查循环

`run()` 方法是模式的入口点，满足 `AgentPattern` 契约。它执行最多 `max_iterations`（默认 3）次计划、执行和目标验证循环。每次迭代遵循相同结构：生成或扩展计划、执行所有当前未阻塞的步骤，然后评估原始目标是否已达成。

在每个阶段边界，协调器检查暂停、中断和待处理延续事件。这确保外部控制信号以最小延迟被遵守，无论当前处于哪个阶段。延续机制值得关注：当用户发送任务中输入时，系统不会硬停止执行，而是将请求记录为 `_pending_continuation`，在下次迭代开始时处理它，干净地扩展现有计划而非丢弃进行中的工作。

**源码参考：** [dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L207-L305)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L638-L720)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L822-L931)

## 阶段一：计划和计划扩展

`PlanGenerator` 负责将自然语言目标（可选地用内存上下文和技能模板增强）转换为由 `PlanStep` 对象组成的结构化 `ExecutionPlan`。存在两个不同操作：**初始生成**（`generate_plan`）和**计划扩展**（`extend_plan`），内部通过 `_generate_plan_with_flow` 统一。

### 计划生成管道

生成器遵循确定性管道：构建提示 → 调用 LLM → 解析结构化响应 → 根据工具可用性验证 → 返回计划。LLM 首先以 JSON 模式调用获取结构化输出；如果解析失败，尝试回退到普通模式调用，随后最多两次重试循环，错误上下文反馈给 LLM 进行自我纠正。

### 计划期间的技能集成

调用 LLM 前，协调器通过 `asyncio.gather` 运行两个并行协程：对 `MemoryStore` 的内存查找（检索相关历史交互）和通过 `SkillManager` 的技能选择（查找领域特定工作流模板）。内存结果通过 `enhance_goal_with_memory` 合并到目标字符串，而技能上下文注入到计划提示。这种并行确保 LLM 调用在两个查找完成时立即开始，互不阻塞。

**源码参考：** [dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L406-L520)，[plan_generator.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/plan_generator.py#L65-L170)，[plan_generator.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/plan_generator.py#L468-L520)，[plan_generator.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/plan_generator.py#L1085-L1090)

### 计划扩展和不可变性

当目标检查器确定目标尚未达成（或用户发送延续输入）时，后续迭代调用 `extend_plan` 而非从头重新生成。这对保留已完成工作至关重要。`ExecutionPlan.extend_with_steps` 方法创建**新**计划实例——原始计划永不修改——追加可引用已完成步骤结果的新步骤。

扩展提示包含完整当前计划、执行历史（由 `ContextBuilder` 自动压缩以避免 token 溢出）和任何用户提供的延续上下文。LLM 被要求分析剩余未完成内容并仅生成所需的额外步骤，通过依赖图将它们连接到现有已完成步骤。

**源码参考：** [models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L225-L234)，[plan_generator.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/plan_generator.py#L540-L710)

## 阶段二：并发 DAG 执行

`PlanExecutor` 实现尊重 DAG 依赖拓扑同时最大化并行性的**队列驱动并发执行引擎**。它使用 `max_concurrency`（默认 4）限制的 `asyncio.Semaphore` 和 `deque` 跟踪准备执行的步骤。

### 执行算法

算法作为处理队列中步骤、派发并发任务、并在每次完成时入队新解锁步骤的连续循环运行：

1. **初始化**：用所有依赖已满足的步骤填充队列（包括前几次迭代已完成的步骤）。
2. **派发**：对队列中每个步骤，通过 `execute_step_with_completion` 启动异步任务，受信号量限制。
3. **完成**：当步骤成功结束时，标记为 `COMPLETED`，记录其结果，查询 `plan.get_executable_steps()` 发现新解锁步骤。
4. **入队**：将任何新解锁步骤加入队列（避免与运行中/已完成/跳过集合重复）。
5. **终止**：队列为空且无运行任务时循环退出，或检测到死锁/超时。

### 依赖解析和分支选择

`PlanStep.can_execute()` 方法实现核心依赖逻辑。当**所有**声明的依赖出现在 `completed_steps` 或 `skipped_steps` 集合中时，步骤变为可执行。对于条件分支——父步骤定义 `conditional_branches` 将分支键映射到下一步骤 ID——`ExecutionPlan.active_branches` 字典跟踪每个条件节点选择了哪个分支。声明 `required_branch` 属性的子步骤只在父级选定分支匹配其要求时才变为可执行。

此机制使 DAG 能表达条件工作流：决策步骤分析数据并选择分支（如 `{"human": "human_response_step", "kb": "kb_search_step"}`），只有所选分支上的步骤被激活。

### 死锁检测

每次派发循环前，执行器运行 `_check_deadlock`，分析保持 `PENDING` 的步骤并使用 DFS 检查未解析依赖是否形成循环链（`_detect_circular_dependencies`）。如果检测到死锁，执行以错误终止而非无限挂起。

**源码参考：** [plan_executor.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/plan_executor.py#L80-L200)，[models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L78-L116)，[plan_executor.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/plan_executor.py#L871-L938)，[models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L152-L204)

## 每步骤智能体执行

每个计划步骤不直接由执行器执行，而是委托给 `StepAgentFactory` 创建的**专用 ReAct 智能体**。这是刻意的设计决策：DAG 模式处理协调和依赖管理，而 [ReAct 模式](https://zread.ai/xorbitsai/xagent/8-react-pattern)处理每个步骤内实际的工具使用推理。

### 基于难度的 LLM 选择

工厂检查每个步骤的 `difficulty` 字段（`"easy"` 或 `"hard"`，默认 `"hard"`）。如果步骤标记为简单且配置了 `fast_llm`，步骤智能体使用更快（通常更小/更便宜）的模型。困难步骤总是使用主 `llm`。这种分层方法优化成本和延迟：简单步骤如文件查找或基本计算使用轻量模型，而复杂分析步骤获得完整推理能力。

每个步骤智能体创建为包装 `ReActPattern` 的完整 `Agent` 实例，并接收：

- 选定的 LLM（基于难度）
- 过滤的工具子集（仅 `step.tool_names` 中声明的）
- 共享的 `Tracer`、`TaskWorkspace` 和 `MemoryStore`
- 长时间步骤执行期间上下文压缩用的 `compact_llm`

**源码参考：** [step_agent_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/step_agent_factory.py#L21-L80)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L1435-L1452)

### 步骤前后注入钩子

模式支持通过 `add_step_injection` 在步骤边界注入自定义逻辑。`StepInjection` 持有可选的 `pre_hook` 和 `post_hook` 可调用对象：

- **前置钩子**：接收步骤描述和依赖上下文；返回修改后的描述字符串。用于注入用户特定指令或动态上下文。
- **后置钩子**：接收步骤结果和依赖上下文；返回修改后的结果字典。用于结果转换、过滤或增强。

这些钩子由执行器在每个步骤的 ReAct 智能体执行前后立即调用，无需子类化即可定制。

**源码参考：** [models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L33-L38)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L1454-L1481)

## 阶段三：目标达成检查

`ResultAnalyzer` 执行单次 LLM 调用，同时评估目标达成、生成综合最终答案并提取内存存储洞察。这种统一调用避免三次单独 LLM 调用，确保目标判定与呈现答案之间的一致性。

### 综合检查

`check_goal_achievement` 方法构建包含原始目标、汇总执行历史（含每个步骤的实际内容）和产生的任何文件输出的提示。它请求 LLM 返回结构化响应：

| 字段 | 类型 | 描述 |
| --- | --- | --- |
| `achieved` | `bool` | 原始目标是否已满足 |
| `reason` | `str` | 达成状态解释 |
| `confidence` | `float` | 0.0 到 1.0 之间的置信度 |
| `final_answer` | `str` | 如已达成，面向用户的综合答案 |
| `memory_insights` | `dict` | 为未来任务相似性建议存储的记忆 |

如果 `achieved` 为 `True`，协调器存储 `final_answer` 并跳出迭代循环。如果为 `False`，循环继续下次迭代（最多 `max_iterations`）。无论达成状态如何，内存洞察都异步存储，馈入[内存存储架构](https://zread.ai/xorbitsai/xagent/17-memory-store-architecture)用于未来计划增强。

**源码参考：** [result_analyzer.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/result_analyzer.py#L34-L100)，[result_analyzer.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/result_analyzer.py#L233-L380)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L863-L925)

## 执行生命周期控制

模式暴露丰富的生命周期管理 API，使外部消费者（主要是 [WebSocket 实时通信](https://zread.ai/xorbitsai/xagent/22-websocket-real-time-communication)层）能在运行时控制执行。

### 暂停、恢复、中断和延续

四个控制原语使用 `asyncio.Event` 和 `asyncio.Condition` 实现：

- **`pause_execution(reason)`**：设置内部 `asyncio.Event`。运行循环的每个阶段边界检查此标志并在 `Condition.wait()` 上阻塞直到清除。
- **`resume_execution()`**：清除暂停事件，唤醒所有阻塞协程。
- **`interrupt_execution(reason)`**：设置 `_execution_interrupted = True`。与暂停不同，这是硬停止——运行循环在下一阶段边界跳出而不等待恢复。
- **`request_continuation(additional_task, context)`**：记录待处理延续请求。下次迭代开始时，计划阶段用新步骤扩展当前计划以处理额外任务，保留所有先前已完成工作。

延续机制对对话式工作流特别重要，用户在执行中提供额外上下文或修改需求。系统优雅地将新输入合并到现有执行图而非取消和重启。

**源码参考：** [dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L1022-L1106)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L149-L157)

## 数据模型：计划步骤和执行计划

`ExecutionPlan` 和 `PlanStep` 数据类构成 DAG 结构的不可变骨干。

### PlanStep 生命周期和能力

每个 `PlanStep` 通过 `StepStatus` 枚举跟踪其完整生命周期（`PENDING → RUNNING → COMPLETED | FAILED | SKIPPED`），包括 `started_at` 和 `completed_at` 时间戳，以及失败时的详细错误信息（`error`、`error_type`、`error_traceback`）。

除基本依赖外，步骤支持两种高级能力：

**条件分支**：步骤可声明 `conditional_branches`——将分支键映射到下一步骤 ID 的字典。当步骤执行并选择分支时，计划将其记录在 `active_branches` 中。下游步骤声明 `required_branch` 表示它们属于哪个分支，`can_execute()` 相应过滤。

**工具范围**：每个步骤声明 `tool_names`——它需要访问的工具标识符列表。执行器用 `_get_tools_for_step` 过滤全局工具映射，确保每个步骤智能体只看到其允许的工具。这防止步骤意外误用不相关工具。

### ExecutionPlan 不可变性和扩展

`ExecutionPlan` 设计为实践中有效不可变。`extend_with_steps` 方法创建带有递增迭代计数器的新 `ExecutionPlan` 实例，将原始步骤与新步骤连接。`get_executable_steps` 方法通过对照已完成和跳过集合加活动分支映射检查每个步骤的 `can_execute()` 来计算当前前沿。

**源码参考：** [models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L11-L72)，[models.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/models.py#L152-L234)，[dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L1424-L1452)

## 配置参数

`DAGPlanExecutePattern.__init__` 接受调节模式行为的综合配置选项集：

| 参数 | 类型 | 默认值 | 描述 |
| --- | --- | --- | --- |
| `llm` | `BaseLLM` | _必需_ | 计划、目标检查和困难步骤用的主模型 |
| `max_iterations` | `int` | `3` | 最大计划-执行-检查循环次数 |
| `goal_check_enabled` | `bool` | `True` | 是否验证目标达成（禁用则即发即忘） |
| `max_concurrency` | `int` | `4` | 信号量限制的并发步骤执行数 |
| `fast_llm` | `BaseLLM | None` | `None` | 简单难度步骤用的轻量模型 |
| `compact_llm` | `BaseLLM | None` | 回退到 `llm` | 上下文压缩专用模型 |
| `context_compact_threshold` | `int | None` | `None` | 触发上下文压缩的 token 数 |
| `memory_store` | `MemoryStore | None` | `None` | 启用跨步骤和跨任务内存 |
| `skill_manager` | `SkillManager | None` | 自动创建 | 提供领域特定计划模板 |
| `allowed_skills` | `List[str] | None` | `None` | 将技能过滤为允许子集 |
| `workspace` | `TaskWorkspace` | _必需_ | 步骤智能体的文件输出目录 |
| `tracer` | `Tracer | None` | 自动创建 | 可观测性用的事件追踪 |
| `step_agent_factory` | `Callable | None` | 内部默认 | 自定义步骤智能体创建覆盖 |

**源码参考：** [dag_plan_execute.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py#L82-L205)

## 与基于图的工作流系统的关系

DAG 计划-执行模式和[图模型与节点](https://zread.ai/xorbitsai/xagent/10-graph-model-and-nodes)系统服务互补但不同的目的。图系统提供预定义、验证的工作流结构（`Graph`、`GraphNode`、`GraphWalker`），通常由开发者或模板设计师编写。它支持 IO 验证、模式强制和访问者模式遍历机制。相比之下，DAG 计划-执行模式通过 LLM 推理在运行时动态生成执行图，计划结构从模型对任务的理解中涌现，而非来自预先编写的规范。

两个系统共享依赖有序执行的概念，但图系统通过 `GraphValidator` 强制结构约束（检测悬空节点、缺失开始/结束节点和模式违规），而 DAG 模式通过运行时基于 LLM 的检查和自己的 `can_execute` 依赖解析验证。`GraphNode` 类可在图节点内嵌入紧凑智能体（`BaseAgent`），概念上类似于 `PlanExecutor` 如何将每个步骤委托给 ReAct 智能体——但图系统的节点是静态定义的，而 DAG 步骤是动态生成的且可在执行中扩展。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L28-L55)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L264-L268)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L282-L293)

## 下一步

理解 DAG 计划-执行模式的协调循环后，以下页面提供相关系统的更深入洞察：

- **[ReAct 模式](https://zread.ai/xorbitsai/xagent/8-react-pattern)**——每个计划步骤委托给的每步骤执行引擎
- **[图模型与节点](https://zread.ai/xorbitsai/xagent/10-graph-model-and-nodes)**——用于预定义执行流程的静态图工作流系统
- **[技能管理器与选择](https://zread.ai/xorbitsai/xagent/14-skill-manager-and-selection)**——计划阶段如何选择领域技能
- **[内存存储架构](https://zread.ai/xorbitsai/xagent/17-memory-store-architecture)**——跨 DAG 执行持久化洞察的内存系统