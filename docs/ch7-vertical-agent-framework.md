# 垂直智能体框架

垂直智能体框架（Vertical Agent Framework）是 xagent 用于构建**领域专用智能体**的可扩展架构，将专门构建的工具、精选的系统提示和定制的执行模式封装在清晰的抽象背后。与通过运行时零散参数配置通用智能体不同，垂直智能体将所有领域智能捆绑到工厂可按需实例化的单一自包含类中。本文追溯框架从抽象契约到工厂注册、生命周期执行以及与更广泛的技能和模板生态系统的集成。

## 架构概览

框架遵循经典的**抽象工厂 + 模板方法**模式。`VerticalAgent` ABC 定义四个抽象钩子——领域工具、领域模式、领域提示和领域名称——子类必须实现。`VerticalAgentFactory` 维护将字符串标识符映射到 `VerticalAgent` 子类的类级注册表，启用运行时多态实例化。`AgentService` 作为顶级协调器，委托智能体创建给工厂并连接追踪、工作空间和工具配置。

这种分层设计分离三个关注点：**领域封装**（VerticalAgent 子类）、**实例化路由**（VerticalAgentFactory）和**运行时协调**（AgentService + AgentRunner）。结果是添加新的垂直领域只需实现四个抽象方法并注册类——无需修改 AgentService、API 层或前端。

**源码参考：** [vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L1-L22)，[vertical_agent_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L24-L28)，[agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L15-L44)，[service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L199-L223)，[context.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/context.py#L8-L18)

## VerticalAgent 抽象基类

`VerticalAgent` 同时继承 `Agent` 和 `ABC`，位于 [vertical_agent.py:22](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L22)。它在构造函数中强制执行**模板方法**模式：当四个领域特定输入（内存、工具、模式、系统提示）中任何一个没有显式提供时，构造函数委托给相应的抽象钩子。这意味着实现了所有四个钩子的子类可以只传 `name` 和 `llm` 实例化，智能体会自动配置自己。

### 构造函数解析链

[第 33–81 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L33-L81) 的构造函数遵循四步回退序列：

| 参数 | 提供了外部值？ | 解析路径 |
| --- | --- | --- |
| `memory` | 否 | `_get_default_memory()` → `InMemoryMemoryStore()` |
| `tools` | 否 | `_get_domain_tools(**kwargs)` |
| `patterns` | 否 | `_get_domain_patterns(llm, **kwargs)` |
| `system_prompt` | 否 | `_get_domain_prompt(**kwargs)` |

解析后，所有值转发给 `super().__init__()` 填充基础 `Agent` 字段。构造函数还在实例上单独存储 `_domain_config`（所有额外 `kwargs`）和 `_system_prompt`，供下游追踪和上下文系统使用。

### 四个抽象钩子

每个钩子设计为被领域子类覆盖，并接收从构造函数转发的 `**kwargs`，允许领域特定配置流通：

- **`_get_domain_tools(**kwargs) → Sequence[Tool]`**（[第 83 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L83-L94)）——返回默认工具集。文本转 SQL 垂直智能体可能只返回 `PythonExecutor` 和 `DatabaseQueryTool`，而代码审查智能体可能返回 `FileTool` 加 `WebSearchTool`。

- **`_get_domain_patterns(llm, **kwargs) → Sequence[AgentPattern]`**（[第 96 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L96-L110)）——返回执行模式。智能体接收 `llm` 实例以便模式可以用正确的模型配置。需要结构化规划的领域可能返回 `DAGPlanExecutePattern`，更简单的领域可能用 `ReActPattern`。

- **`_get_domain_prompt(**kwargs) → str`**（[第 112 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L112-L123)）——返回系统提示。这是注入领域专业知识的主要机制。提示存储为 `self._system_prompt` 并自动注入到执行上下文供模式消费。

- **`_get_domain_name() → str`**（[第 189 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L189-L197)）——返回用于追踪元数据和错误上下文的人类可读领域标识符。

**源码参考：** [vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L33-L123)，[agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/agent.py#L20-L34)

## 执行生命周期

与将执行完全委托给 `AgentRunner` 的基础 `Agent` 类不同，`VerticalAgent` 在 [第 199 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L199-L254) 用自己的领域感知生命周期覆盖 `execute()`。这个覆盖给垂直智能体控制模式选择、上下文注入、后处理和错误处理的能力——通用运行器不提供的能力。

### 上下文构建

[第 256 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L256-L288) 的 `_build_execution_context()` 方法组装包含 `agent_type`、`domain`、`task` 和 `_system_prompt` 的 `state` 字典。然后合并来自 `_get_domain_context()`（[第 290 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L290-L301) 默认返回 `{}` 的非抽象可覆盖方法）的领域特定上下文和任何额外 `kwargs`。最终输出将状态包装在 `{"state": state}` 中以匹配 `AgentContext` Pydantic 模型结构。

### 后处理

[第 303 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L303-L324) 的 `_post_process_result()` 方法为每个结果标记领域元数据——如果尚未存在，将 `agent_type` 和 `domain` 注入 `result["metadata"]`。子类可覆盖它来转换结果（例如从自由格式 LLM 输出提取结构化 JSON）。

### 领域错误处理

[第 326 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L326-L359) 的 `_handle_domain_error()` 方法实现两层策略：`PatternExecutionError` 实例原样重新抛出（它们已携带结构化上下文），而其他所有异常包装在新的 `PatternExecutionError` 中，上下文字典嵌入领域名称、任务摘要和原始错误类型。这确保通过 `AgentRunner` 异常处理呈现的错误总是携带领域归属。

**源码参考：** [vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L199-L359)，[context.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/context.py#L8-L18)，[exceptions.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/exceptions.py#L117-L132)

## 垂直智能体的追踪集成

垂直智能体通过两个不同于基础 `Agent` 类的专用追踪钩子获得可观测性：

| 方法 | 调用点 | 用途 |
| --- | --- | --- |
| `get_step_trace_data(step_result)`（[第 125 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L125-L141)） | 每个模式步骤完成后 | 为前端追踪事件提取步骤级结构化数据 |
| `get_completion_trace_data(final_result)`（[第 143 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L143-L159)） | 完整执行完成后 | 为完成追踪事件提取最终结果结构化数据 |

两者都返回 `Optional[Dict[str, Any]]`，默认为 `None`，意味着垂直智能体只在有领域特定数据要发射时才加入结构化追踪（例如 SQL 智能体可能返回生成的查询，图表智能体可能返回可视化 URL）。这些钩子馈入更广泛的 `Tracer` 系统，管理具有 [trace.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/trace.py#L13-L47) 定义的 `scope`（`TASK`/`STEP`/`ACTION`）、`action`（`START`/`END`/`ERROR`）和 `category`（`DAG`/`REACT`/`TOOL`/`LLM`）分类的 `TraceEvent` 实例。

[第 172 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L172-L187) 的 `get_domain_info()` 方法提供诊断快照——智能体类名、领域、工具名、模式名和领域配置——对调试和管理仪表板有用。

**源码参考：** [vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L125-L187)，[trace.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/trace.py#L13-L47)

## VerticalAgentFactory：注册表模式

[vertical_agent_factory.py:24](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L24-L28) 的工厂使用**类级字典**（`_vertical_agents: Dict[str, Type[VerticalAgent]]`）作为注册表，配合 `_initialized` 标志用于惰性注册。这个设计有几个重要属性。

### 注册流程

[第 30 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L30-L42) 的 `register_vertical_agent(name, agent_class)` 将名称小写以支持大小写不敏感查找并存储类引用。注册是幂等的——同一名称的后续注册会覆盖先前的。

### 智能体创建逻辑

[第 49 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L49-L128) 的 `create_agent()` 类方法实现三分支调度：

1. **垂直智能体匹配**——如果 `agent_type.lower()` 存在于注册表中，工厂实例化注册的类。关键地，它在传递前从 kwargs 中剥离 `tools`、`patterns` 和 `system_prompt`（[第 91–94 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L91-L94)），因为垂直智能体通过抽象钩子创建自己的。

2. **标准智能体匹配**——如果 `agent_type` 是 `"standard"`、`"agent"` 或 `"default"`，用显式提供的模式和工具创建普通 `Agent`（[第 103–122 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L103-L122)）。

3. **未知类型**——引发 `ValueError` 列出所有可用类型包括已注册的垂直智能体（[第 124–128 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L124-L128)）。

### 惰性初始化

[第 130 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L130-L135) 的 `_ensure_initialized()` 守卫恰好触发 `_register_default_agents()` 一次。目前，[第 137 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L137-L144) 的 `_register_default_agents()` 是 `pass` 占位符，有内联文档说明扩展配方：（1）创建 `VerticalAgent` 子类，（2）导入并注册它。模块还在 [第 147 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L147-L163) 导出 `create_agent()` 便捷函数，直接委托给工厂。

**源码参考：** [vertical_agent_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L24-L164)

## 与 AgentService 的集成

`AgentService` 是工厂的主要消费者，在 [service.py:199–223](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L199-L223) 将垂直智能体创建集成到完整智能体生命周期。服务接受 `agent_type` 参数（默认 `"standard"`）并组装包含 LLM、内存、工具、工作空间、追踪器、task_id、模式、system_prompt 和任何额外 `agent_kwargs` 的配置字典。

[第 220 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L220-L222) 的工厂调用传递此配置，工厂的调度逻辑处理其余部分。创建后，服务遍历 `self.agent.patterns` 将追踪器注入任何有 `tracer` 属性的模式（[第 226–228 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L226-L228)），确保无论智能体是标准还是垂直类型都有统一的可观测性。

实例化垂直智能体时，工厂的 kwarg 过滤意味着服务准备的 `patterns`、`tools` 和 `system_prompt` 被静默丢弃，代之以垂直智能体自己的领域默认值。这是设计如此：垂直智能体断言对其执行配置的完全控制。然而，工作空间、追踪器和 task_id 会流通，因为它们与领域逻辑正交。

服务的 `execute_task()` 方法在 [第 230 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L230-L280) 不区分智能体类型——它统一调用运行器或智能体的 `execute()` 方法，依赖多态 `Agent` 接口。

**源码参考：** [service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L199-L228)，[runner.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/runner.py#L31-L78)

## 与技能和模板系统的关系

虽然垂直智能体与技能/模板系统服务于架构的不同层，但它们有概念上的亲缘关系：两者都旨在减少专门工作流的配置面。

### 技能：模式级配置

**技能系统**（[skills/](https://zread.ai/xorbitsai/xagent/src/xagent/skills/)）在更低抽象层次运作。技能是基于 markdown 的包（`SKILL.md` 文件），包含指令、工具需求和提示模板。[manager.py:16](https://zread.ai/xorbitsai/xagent/src/xagent/skills/manager.py#L16) 的 `SkillManager` 扫描技能目录，[selector.py:12](https://zread.ai/xorbitsai/xagent/src/xagent/skills/selector.py#L12) 的 `SkillSelector` 使用基于 LLM 的匹配为给定任务选择技能。技能通过将专门提示和工具子集注入现有模式（通常是 `DAGPlanExecutePattern`）来影响执行。

关键区别：**技能增强标准智能体的行为**，而**垂直智能体完全替换智能体**。技能按任务动态选择；垂直智能体在智能体创建时确定。[service.py:134–138](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L134-L138) 的 DAG 模式 `allowed_skills` 配置桥接这两个世界——使用 DAG 模式的标准智能体可以将技能选择限制为精选列表。

### 模板：声明式智能体配方

**模板系统**（[templates/](https://zread.ai/xorbitsai/xagent/src/xagent/templates/)）提供基于 YAML 的智能体配方。[manager.py:15](https://zread.ai/xorbitsai/xagent/src/xagent/templates/manager.py#L15) 的 `TemplateManager` 解析 `built_in/` 目录中的 YAML 文件，包含 18 个预配置模板如 `customer_support_agent.yaml`、`delivery_assistant.yaml` 和 `document_translator.yaml`。模板声明式定义智能体配置——名称、描述、工具、系统提示——无需代码。

模板占据中间位置：比技能更结构化但不如垂直智能体强大。模板可以预配置标准智能体的工具和提示，但不能覆盖执行生命周期、实现自定义追踪钩子或定义领域特定的错误处理——所有垂直智能体提供的能力。

| 方面 | 技能 | 模板 | 垂直智能体 |
| --- | --- | --- | --- |
| 抽象层次 | 模式增强 | 智能体配方 | 完整智能体替换 |
| 配置 | Markdown（`SKILL.md`） | YAML 文件 | Python 类（4 个抽象方法） |
| 选择 | 按任务动态（LLM 匹配） | 手动或 API 驱动 | 创建时的 `agent_type` 参数 |
| 执行控制 | 无（注入现有模式） | 无（配置标准智能体） | 完全（覆盖 `execute()`、追踪、错误处理） |
| 可扩展性 | 添加新技能目录 | 添加新 YAML 文件 | 注册新 `VerticalAgent` 子类 |

**源码参考：** [skills/manager.py](https://zread.ai/xorbitsai/xagent/src/xagent/skills/manager.py#L16-L26)，[skills/selector.py](https://zread.ai/xorbitsai/xagent/src/xagent/skills/selector.py#L12-L17)，[templates/manager.py](https://zread.ai/xorbitsai/xagent/src/xagent/templates/manager.py#L15-L23)，[service.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/service.py#L130-L174)

## 定义自定义垂直智能体

实现新的垂直智能体需要三步，都可在不修改现有框架代码的情况下完成：

**步骤一**——创建实现四个抽象钩子的子类。子类控制自己的工具清单、模式选择、提示工程，以及可选的上下文构建、后处理、追踪和错误处理覆盖。

**步骤二**——向工厂注册类，要么在 `_register_default_agents()` 中用于内置领域，要么在应用启动时用于基于插件的领域。

**步骤三**——通过 `AgentService(agent_type="my_domain")` 或 `create_agent()` 便捷函数实例化。工厂路由到正确的类，垂直智能体自配置。

可扩展面被刻意放宽。除四个必需钩子外，垂直智能体子类可覆盖：

- `_get_domain_context(task, **kwargs)` 将任务特定状态注入执行上下文（[第 290 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L290-L301)）
- `_get_default_memory()` 提供领域特定的内存后端（[第 161 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L161-L170)）
- `_post_process_result(result, task, **kwargs)` 转换原始执行输出（[第 303 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L303-L324)）
- `_handle_domain_error(error, task, **kwargs)` 用于自定义错误恢复（[第 326 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L326-L359)）
- `get_step_trace_data()` 和 `get_completion_trace_data()` 用于领域特定可观测性（[第 125–159 行](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L125-L159)）

**源码参考：** [vertical_agent.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent.py#L22-L359)，[vertical_agent_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/agent/vertical_agent_factory.py#L137-L144)

## 下一步

本文涵盖了垂直智能体抽象及其基于工厂的实例化。要理解基础 `Agent` 类如何提供子智能体嵌套和执行历史——垂直智能体继承的能力——请参阅[基础智能体模型](https://zread.ai/xorbitsai/xagent/5-base-agent-model)。关于智能体如何在运行时通过模式驱动，继续阅读[智能体运行器执行](https://zread.ai/xorbitsai/xagent/6-agent-runner-execution)。要探索垂直智能体通过 `_get_domain_patterns()` 选择的执行策略，请参阅 [ReAct 模式](https://zread.ai/xorbitsai/xagent/8-react-pattern)和[DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)。对于垂直智能体通过 `_get_domain_tools()` 配置的工具系统，请参阅[内置核心工具](https://zread.ai/xorbitsai/xagent/12-built-in-core-tools)。
