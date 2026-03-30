# 图遍历器与验证

本文研究 XAgent 中确保基于图的工作流在执行前结构健全和语义正确的运行时遍历引擎和多层验证管道。`GraphWalker` 和 `GraphValidator` 共同构成安全网，在定义时而非运行时捕获拓扑错误、模式不一致和数据流不匹配。

## 架构概览

图子系统遵循遍历与验证关注点分离的分层架构。`GraphWalker` 提供通用深度优先遍历原语，而 `GraphValidator` 在该遍历上组合多个验证通道——结构、拓扑和 I/O 契约。`Graph` 模型本身也暴露编排所有验证阶段的更高层 `validate_graph()` 外观。

## GraphWalker —— 通用遍历引擎

`GraphWalker` 是独立的遍历类，使用显式基于栈的深度优先策略从 `StartNode` 开始遍历 `Graph`。它接受在遍历期间为每个节点调用的访问者函数，接收当前节点和累积数据载荷。访问者的返回值成为下游节点的数据载荷，启用模式累积等有状态遍历模式。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L282-L336)

### 遍历机制

遍历器通过从图节点列表构建内部 `_node_map` 字典以支持按 ID 的 O(1) 查找来初始化。然后识别第一个 `StartNode` 并开始栈驱动遍历。关键设计决策：

1. **显式栈而非递归**：避免 Python 在深图上的递归限制，提供可预测的内存行为。
2. **已访问集合守卫**：每个节点跟踪在 `visited: set[str]` 中，防止循环图上的无限循环（虽然 `Graph` 上的 `allow_cycles` 标志语义上允许能处理循环的执行引擎使用）。
3. **多态边解析**：遍历器根据节点目标类型分发——`SingleDestNode`、`MultiDestNode` 或 `CondDestNode`——解析正确的后继 ID 集合。这与运行时执行时 `Graph.get_next_nodes()` 使用的相同分发逻辑。

```python
stack: list[tuple[Node, Any]] = [(start_nodes[0], initial_data)]
while stack:
    current, data = stack.pop()
    if current.id in visited:
        continue
    visited.add(current.id)
    data = visitor_func(current, data)
    # 根据节点类型分发推送后继...
```

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L290-L336)

### 访问者契约

访问者函数签名是 `Callable[[Node, Any], Any]`。它接收当前节点和累积数据载荷，必须返回（可能修改的）数据以转发给后继节点。此契约使遍历器能作为多种验证策略的骨干而无需修改遍历逻辑本身。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L290-L292)

### 节点目标类型和边解析

遍历器必须处理三种不同的边模式，每种在 [node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L31-L73) 中定义：

| 边类型 | 类 | `next` 字段类型 | 解析逻辑 |
| --- | --- | --- | --- |
| 单目标 | `SingleDestNode` | `str` | 直接查找：`node_map[next]` |
| 多目标 | `MultiDestNode` | `str | list[str]` | 遍历所有 ID，跳过 `None` 或缺失 |
| 条件 | `CondDestNode` | `list[dict]` | 从每条规则提取 `"default"` 或 `"branch"` 键 |

对于 `MultiDestNode`，`@field_validator` 预先将字符串值包装成列表以防止 Pydantic 将 `"END"` 迭代为 `['E', 'N', 'D']`——这是 [node.py L46-L57](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L46-L57) 的微妙但关键守卫。

**源码参考：** [node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L31-L73)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L322-L335)

## GraphValidator —— 结构完整性检查

`GraphValidator` 是专用结构验证器，用 `Graph` 实例化，内部构建 `GraphWalker` 用于拓扑分析。它执行四个顺序检查，首次违规立即失败。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L339-L395)

### 验证序列

`validate()` 方法按严格顺序执行检查，每个引发 `GraphValidationError` 的特定错误子类：

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L364-L395)

### 1. 重复节点 ID 检测

验证器扫描所有节点 ID 并报告任何出现多次的。这防止边指向节点 ID 时的歧义引用。检测使用列表计数方法：对集合交集中发现的每个唯一 ID 检查 `node_ids.count(id) > 1`。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L350-L357)

### 2. 终端节点约束

结构良好的图必须恰好包含一个 `StartNode` 和至少一个 `EndNode`。验证器强制：

- **零开始节点** → `MissingStartNodeError`——遍历器无入口点。
- **多个开始节点** → `DuplicatedStartNodeError`——执行来源歧义。
- **零结束节点** → `MissingEndNodeError`——图无终止条件。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L379-L390)

### 3. 悬空节点检测

悬空节点是无法通过图的边连接从 `StartNode` 到达的节点。验证器使用带无操作访问者（`lambda *args, **kwargs: None`）的 `GraphWalker` 收集所有访问节点，然后与完整节点集求差。任何未访问的节点报告为悬空。

此检查捕获可能永无法执行的孤立子图，这对从 YAML 解析的图特别重要，因为 `next` 字段中的拼写错误可能静默断开节点连接。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L359-L362)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L392-L394)

## I/O 契约验证

除拓扑正确性外，XAgent 验证连接节点间的数据契约是否满足。这在 [io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py) 中使用遍历图同时累积可用输出属性的递归结构比较算法实现。

**源码参考：** [io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L1-L115)

### I/O 验证如何工作

验证由 `Graph.validate_input_output()` 触发，它调用 `_traverse_graph` 并传入由 `get_validate_input_output_fn()` 创建的访问者。此访问者维护演变的"可用属性"字典——上游节点产生的所有输出模式属性的并集。对于每个有 `input_schema` 的节点，它递归检查必需输入属性是否是可用属性的子集。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L127-L128)，[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L91-L112)

### 递归结构比较

核心算法 `validate_recursive` 按四条顺序规则检查必需属性对可用属性：

| 检查 | 描述 | 抛出错误 |
| --- | --- | --- |
| **常量字段** | 有 `"const"` 键的字段自满足并跳过 | 无 |
| **全常量对象** | 每个嵌套属性都是常量的对象类型被视为自满足 | 无 |
| **字段存在** | 必需字段必须存在于可用属性中 | 带路径的 `MismatchInputOutputError` |
| **类型兼容** | 如果两者定义 `type`，必须完全匹配 | 带类型信息的 `MismatchInputOutputError` |
| **嵌套递归** | 有嵌套 `properties` 的对象类型字段递归验证 | 从内部调用传播 |

算法在错误消息中使用点分隔路径（如 `"user.email"`）精确定位嵌套结构中契约违规的确切位置。

**源码参考：** [io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L23-L71)

### 深度合并策略

当节点产生输出属性时，它们被**深度合并**到累积可用属性中。如果键的现有定义和传入定义都是对象类型，它们的 `properties` 子字典递归合并而非覆盖。这启用管道模式：节点 A 产生 `user.name`，节点 B 产生 `user.email`，下游节点 C 可以要求完整的 `user` 对象。

实现在每个分支点对可用属性使用 `deepcopy` 后合并，确保图中分支路径不会污染彼此的累积状态。

**源码参考：** [io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L73-L89)，[io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L105-L106)

### 输入覆盖

节点可声明 `input_overrides`——字段名到 `InputOverride` 对象的映射，带 `source: "state_args"`。I/O 验证期间，覆盖键从必需属性检查中排除，因为这些字段由运行时状态注入提供而非上游节点输出。这允许灵活连接，部分输入来自图数据流，其他来自外部状态。

**源码参考：** [io_validation.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/io_validation.py#L94-L98)，[node.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/node.py#L13-L17)

## 模式验证

`SchemaParser` 类验证 `Graph` 中所有声明的模式符合 JSON Schema Draft 7 格式。它在 `Graph` 构造时（通过 `schemas` 上的 `@field_validator`）和 `validate_graph()` 中再次被调用。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L35-L48)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L130-L145)，[schema.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/schema.py#L7-L45)

### 模式规范化

`SchemaParser._normalize_schemas()` 确保每个模式有 `title` 和 `description` 字段，缺失时两者都默认为模式 ID。此规范化使模式自文档化并与期望完整元数据的工具兼容。

**源码参考：** [schema.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/schema.py#L22-L34)

### 验证执行点

模式验证在生命周期中两个不同点发生：

| 生命周期点 | 触发器 | 效果 |
| --- | --- | --- |
| **图构造** | `@field_validator("schemas")` | 完全阻止创建无效图 |
| **显式验证** | `Graph.validate_schemas()` | 重新验证以深度防御，如程序化修改后 |

两者使用 `jsonschema` 库的 `Draft7Validator.check_schema()` 并在消息中嵌入违规模式 ID 抛出 `SchemaError`。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L35-L48)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L130-L145)

## 统一验证入口点

`Graph.validate_graph()` 是消费者调用以验证完整图定义的单一方法。它按顺序委托给三个子系统：

这五阶段管道确保通过 `validate_graph()` 的图在任何执行引擎处理前结构完整、拓扑连通、契约一致且模式合规。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L147-L160)

## 错误层次

所有图验证错误继承自 `GraphValidationError`，使消费者能用单个异常处理器捕获整个类别或按特定子类型分发进行细粒度错误报告。

| 错误类 | 条件 | 关键载荷 |
| --- | --- | --- |
| `DuplicateNodeError` | 两个或更多节点共享 ID | `node_ids: list[str]` |
| `MissingStartNodeError` | 未找到 `StartNode` | — |
| `DuplicatedStartNodeError` | 多于一个 `StartNode` | — |
| `MissingEndNodeError` | 未找到 `EndNode` | — |
| `DanglingNodeError` | 从开始不可达的节点 | `node_ids: list[str]` |
| `InvalidSchemaIDError` | 引用的模式不存在 | `schema_id`, `available_schema_ids` |
| `MismatchInputOutputError` | 输入契约不满足 | `node_id`, 描述性路径 |
| `InvalidInputOutputPathError` | 畸形状态路径表达式 | `path: str` |
| `NonParallelizableNodeError` | 节点缺少 `Parallelizable` 标记 | `node` 引用 |

**源码参考：** [error.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/error.py#L1-L55)

## GraphNode 和子图遍历

`GraphNode` 表示在父工作流中包装整个 `Graph` 作为子图的节点。它扩展 `MultiDestNode` 和 `DeterministicEdge`，携带控制子图如何与父状态命名空间交互的 `StateMode`。

### StateMode 配置

`GraphNode` 上的 `mode` 字段决定父子图间的双向状态可见性：

| 模式 | 值 | 行为 |
| --- | --- | --- |
| `NONE` | 0 | 无状态共享——子图隔离运行 |
| `READ` | 1 | 子图可读父状态但不能修改 |
| `WRITE` | 2 | 子图可写父状态但不能读现有值 |
| `READWRITE` | 3 | 完全双向状态访问（默认） |

模式从 YAML 配置接受字符串值（大小写不敏感如 `"read"`、`"WRITE"`）和整数值（`0`–`3`），由构造时的 `@field_validator` 解析。

**源码参考：** [graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L246-L279)，[graph.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/graph.py#L264-L268)

### 解析期间的子图解析

[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py) 中的 YAML 解析器使用三遍策略处理子图引用：

1. **第一遍**——创建有模式和元数据但无节点的空 `Graph` 壳。
2. **第二遍**——解析所有节点定义，通过 `NodeFactory` 解析内置类型并为子图引用创建 `GraphNode` 包装器。
3. **第三遍**——解析 `GraphNode.graph.nodes` 指向第二遍的实际解析节点列表，因为图之间的前向引用需要两者都先存在。

**源码参考：** [parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L85-L115)

## 与图解析的关系

虽然本文聚焦运行时遍历器和验证器，验证管道与基于 YAML 的图解析器紧密耦合。[parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py) 中的 `parse_graphs()` 函数在解析期间执行早期验证——通过 `validate_tools()` 的工具配置验证和通过 `NodeFactory.create_node()` 的 Pydantic 模型验证——在上述结构验证可达之前。这创建深度防御模式，畸形的图在最早可能阶段被拒绝。

**源码参考：** [parse.py](https://zread.ai/xorbitsai/xagent/src/xagent/core/graph/parse.py#L13-L82)

## 下一步

- **[图模型与节点](https://zread.ai/xorbitsai/xagent/10-graph-model-and-nodes)**——理解遍历器遍历的节点类型层次、混入和 `NodeFactory` 注册系统。
- **[DAG 计划-执行循环](https://zread.ai/xorbitsai/xagent/9-dag-plan-execute-loop)**——查看验证后的图如何由智能体运行器在运行时执行。
- **[内置核心工具](https://zread.ai/xorbitsai/xagent/12-built-in-core-tools)**——探索用可执行行为填充验证图的工具节点。