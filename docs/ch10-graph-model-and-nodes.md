# 图模型与节点

XAgent 的图系统是其工作流协调的骨干——一个声明式、YAML 驱动的引擎，将静态配置转换为可执行的智能体管道。与其命令式编写控制流，你定义**节点**（工作单元）和**边**（它们之间的连接），图运行时处理遍历、验证和状态传播。本文剖析结构模型、完整节点类型层次和确保执行前图完整性的验证机制。

## 图结构模型

核心上，`Graph` 是一个 Pydantic `BaseModel`，作为单个工作流定义的自包含容器。每个图携带唯一 `graph_id`、有序 `Node` 实例列表、可选的输入/输出契约 `schemas` 字典，以及设置 `True` 时放宽默认 DAG 强制的 `allow_cycles` 标志[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L28-L33)。

`Graph` 类维护在 `model_post_init` 中构建的内部 `_node_map`（`dict[str, Node]`），提供按 ID 的 O(1) 节点查找[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L52-L53)。`node_map()` 方法是按需重建此映射的公共访问器[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L55-L56)。

图遍历由通用 `_traverse_graph` 方法处理，它接受访问者函数和初始数据，然后从 `StartNode` 开始执行基于栈的 DFS。遍历根据节点目标类型分支——`SingleDestNode` 遵循单个 `next` 边，`MultiDestNode` 扇出到多个目标，`CondDestNode` 从其规则字典提取目标 ID[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L67-L118)。同样的访问者模式驱动 `get_dangling_nodes` 分析和输入/输出模式验证。

### 子图与 GraphNode

当工作流需要组合时，XAgent 通过 `GraphNode` 类支持**子图**。`GraphNode` 包装整个 `Graph` 实例并作为单个节点参与父图。它携带继承边行为外的三个额外字段：`compact` 智能体（用于汇总子图输出的可选 `BaseAgent`）、控制状态访问语义的 `mode` 字段，以及交互提示的 `human_message`[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L264-L268)。

`StateMode` 枚举为子图定义四级状态隔离：`NONE`（无状态访问）、`READ`（只读）、`WRITE`（只写）和 `READWRITE`（完全访问，默认）。此模式灵活从 YAML 解析——接受 `"read"`、`"write"`、`"readwrite"` 等字符串、整数 `0`–`3` 或原始 `StateMode` 枚举值[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L246-L261)。

## 节点类型层次

XAgent 中的节点通过**可组合混入**而非深层继承树构建。每种节点类型由一小组成员能力组装：路由行为、模式契约和行为标记。这种设计保持单个类精简并最大化可重用性。

### 三种路由维度

每个有出边的节点实现 `WithNextIds` 抽象接口，要求 `get_node_ids()` 方法。具体路由行为由三个类捕获：

- **`SingleDestNode`**——通过 `next: str` 字段路由到恰好一个后继[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L36-L40)。
- **`MultiDestNode`**——通过 `next: Union[str, list[str]]` 字段路由到一个或多个后继。关键地，`@field_validator` 将裸字符串包装成列表以防止 Pydantic 将 `"END"` 迭代为 `['E', 'N', 'D']`[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L43-L57)。
- **`CondDestNode`**——通过 `next: list[dict[str, Any]]` 字段基于条件规则路由，每个字典包含指向目标节点 ID 的 `"default"` 或 `"branch"` 键[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L60-L70)。

### 行为标记

两个标记类不携带字段但编码系统其他地方检查的语义约束：

- **`DeterministicEdge`** 标识节点的出边是固定的（非条件）。执行运行时用此区分决定是自动跟随边还是咨询路由函数[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L73-L74)。
- **`Parallelizable`** 标记有资格并行执行的节点（map/fork 操作）。尝试并行化非 `Parallelizable` 节点触发 `NonParallelizableNodeError`[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L77-L85)。

### 模式混入

三个轻量 Pydantic 模型为节点附加模式契约：

| 混入 | 字段 | 用途 |
| --- | --- | --- |
| `InputSchema` | `input_schema: str | None`, `input_overrides: dict | None` | 声明节点输入必须符合的 JSON Schema ID；覆盖允许注入静态或状态派生值 |
| `OutputSchema` | `output_schema: str | None` | 声明描述节点输出形状的 JSON Schema ID |
| `BoundSchema` | `bound_schema: str | None` | 用于 `MapNode` 定义并行批处理内项目的模式契约 |

这些混入引用模式 ID 而非内联定义，保持节点配置简洁，同时模式集中存储在父级 `Graph.schemas` 字典中[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L18-L28)。

## 完整节点类型参考

每个具体节点类型通过 `@NodeFactory.register("type_name")` 装饰器向 `NodeFactory` 注册。这使 YAML 解析器能从字符串类型标识符实例化节点[node_factory.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node_factory.py#L14-L29)。

| 类型键 | 类 | 混入 | 用途 |
| --- | --- | --- | --- |
| `start` | `StartNode` | `MultiDestNode`, `OutputSchema`, `DeterministicEdge` | 固定 `id = "START"` 的入口点 |
| `end` | `EndNode` | `InputSchema` | 固定 `id = "END"` 的终端节点 |
| `agent` | `AgentNode` | `BaseAgent`, `MultiDestNode`, `InputSchema`, `DeterministicEdge`, `Parallelizable` | 带模型配置和可选 `ai_state_args` 的 LLM 驱动智能体 |
| `tool_agent` | `ToolAgentNode` | 扩展 `AgentNode` + `InputSchema`, `Parallelizable` | 配备工具的智能体；支持 `max_tool_call`, `need_summary`, `summary_prompt` |
| `tool` | `ToolNode` | `MultiDestNode`, `InputSchema`, `OutputSchema`, `DeterministicEdge`, `Parallelizable` | 通过 `tool_name` 执行单个工具，可选 `init_info` |
| `tool_conditional` | `ToolConditionalNode` | `CondDestNode`, `InputSchema`, `OutputSchema` | 运行工具然后通过条件 `next` 规则基于结果路由 |
| `agent_conditional` | `AgentConditionalNode` | `BaseAgent`, `MultiDestNode`, `InputSchema` | 带 `ai_state_args` 的 LLM 驱动路由节点 |
| `embedding` | `EmbeddingNode` | `MultiDestNode`, `DeterministicEdge`, `Parallelizable` | 使用 `model_id` 和可配置 `input_field` 状态路径生成嵌入 |
| `dashscope_rerank` | `DashScopeRerankNode` | `MultiDestNode`, `DeterministicEdge`, `Parallelizable` | 通过 DashScope API 重排文档，带 `model_id`, `input_field`, `query_field`, `top_k` |
| `structured_agent` | `StructuredAgentNode` | `SingleDestNode`, `BaseAgent`, `InputSchema`, `OutputSchema`, `DeterministicEdge` | 约束为结构化输出模式的智能体 |
| `map` | `MapNode` | `MultiDestNode`, `DeterministicEdge`, `InputSchema`, `OutputSchema`, `BoundSchema` | 带 `chunk_size` 控制的项目并行执行 |

`BaseAgent` 混入（由 `AgentNode`、`ToolAgentNode`、`StructuredAgentNode` 和 `AgentConditionalNode` 共享）定义三个核心 LLM 参数：`model_id`（必需）、`temperature`（限制在 0–2）和 `system_prompt`（必需）[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L98-L101)。

## YAML 解析管道

图定义通过 `parse_graphs` 实现的三遍解析策略从 YAML 文件流向运行时就绪的 `Graph` 对象[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L85-L115)。

**第一遍**创建空的 `Graph` 壳，填充 `graph_id`、`schemas` 和 `allow_cycles` 但 `nodes=[]`。这确保后续遍历中的任何子图引用可以解析到这些壳[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L89-L98)。

**第二遍**遍历所有图定义并解析每个节点配置字典。`parse_node` 函数首先尝试 `NodeFactory.create_node(node_type, **yaml_data)` 处理内置节点类型；如果返回 `None`，检查类型是否匹配子图 ID 并将其包装在 `GraphNode` 中。特殊兼容性垫片将 `"nexts"` → `"next"` 映射到 `agent_conditional` 节点[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L51-L82)。

**第三遍**通过设置 `node.graph.nodes` 指向对应子图的完整填充节点列表来解析 `GraphNode` 引用，完成父子图之间的循环依赖[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L110-L113)。

`ToolAgentNode` 配置内的工具验证由 `validate_tools` 处理，它将 YAML 的 `tools` 字典列表转换为 `ToolAgentNode.__init__` 期望的 `list[tuple[str, Optional[dict]]]` 格式[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L13-L48)。

## 验证架构

图验证系统在三个不同层运作，每层捕获特定类别的结构错误。`GraphValidator` 类协调结构检查，而 `Graph.validate_input_output()` 处理模式级 I/O 契约，`Graph.validate_schemas()` 验证 JSON Schema 合规性。

### 结构验证

`GraphValidator.validate()` 按顺序运行四个检查，首次失败立即抛出[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L364-L394)：

| 检查 | 抛出错误 | 条件 |
| --- | --- | --- |
| 重复 ID | `DuplicateNodeError` | 两个或更多节点共享相同 `id` |
| 缺失开始 | `MissingStartNodeError` | 未找到 `StartNode` |
| 重复开始 | `DuplicatedStartNodeError` | 多于一个 `StartNode` |
| 缺失结束 | `MissingEndNodeError` | 未找到 `EndNode` |
| 悬空节点 | `DanglingNodeError` | 无法通过从 `StartNode` 遍历到达的节点 |

悬空节点检查执行完整图遍历并将访问节点与完整节点集比较，报告任何与主路径断开的节点[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L359-L362)。

### 输入/输出模式验证

I/O 验证器是最复杂的层。它通过遍历图同时累积"可用属性"字典工作——上游节点产生的所有输出模式的深度合并视图。对每个有 `input_schema` 的节点，它递归检查每个必需字段是否被累积属性满足[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L8-L114)。

递归比较按顺序遵循四条规则：

1. **`const` 字段自满足**——输入模式中标记 `"const": "value"` 的字段被跳过，因为它们代表节点自身注入的固定值[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L43-L45)。
2. **存在性检查**——输入模式中每个非常量字段必须存在于可用属性中。如果对象类型的整个定义由常量子属性组成，则例外[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L47-L54)。
3. **类型检查**——如果需求和提供的定义都指定 `type`，它们必须完全匹配[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L60-L65)。
4. **递归下降**——对于有嵌套 `properties` 的 `type: "object"` 字段，验证器递归进入嵌套结构，产生路径注释的错误消息如 `Missing required field, current path: 'user.email'`[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L68-L71)。

`merge_properties` 函数将输出属性深度合并到累积状态中，处理嵌套对象融合——所以如果一个节点输出 `user.name` 而另一个输出 `user.email`，合并状态包含两者在单个 `user` 对象下[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L73-L89)。

### JSON Schema 验证

模式在两方面验证。`Graph` 构造期间，`schemas` 字段的 `@field_validator` 通过 `Draft7Validator.check_schema()` 运行每个模式并通过 `SchemaParser` 规范化（缺失时自动从模式 ID 注入 `title` 和 `description`）[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L35-L48)。`validate_schemas()` 方法提供图构造后的显式重检可调用[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L130-L145)。

### 错误层次

所有验证错误继承自 `GraphValidationError`，为错误处理提供结构化分类[error.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/error.py#L1-L55)：

## 下一步

理解图模型的结构、节点类型和验证机制后，自然的下一步是探索这些图如何在**运行时实际执行**——驱动节点到节点推进的遍历器、节点间流动的状态管理，以及条件路由决策如何解析。这个故事在[图遍历器与验证](https://zread.ai/xorbitsai/xagent/11-graph-walker-and-validation)中展开。

关于图系统如何适配智能体执行层的更广视角，请参阅[智能体运行器执行](https://zread.ai/xorbitsai/xagent/6-agent-runner-execution)。如果你对能动态生成类图执行计划的规划引擎感兴趣，请参阅[DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)。