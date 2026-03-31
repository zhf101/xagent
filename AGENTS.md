# Xagent Agent System

Xagent is a powerful and flexible framework for building and running AI-powered agents with support for various execution patterns, tools, memory management, and observability.

## Features

- **Agent Patterns**: ReAct, DAG plan-execute
- **Nested Agents**: Hierarchical agent execution with parent-child relationships
- **Tool System**: Built-in tools with auto-discovery mechanism
- **Memory Management**: LanceDB-based vector storage with semantic search
- **Observability**: Langfuse integration for tracing and monitoring
- **Real-time Communication**: WebSocket support for agent execution monitoring


## 编码原则

- 实现优先级：正确性 > 可验证性 > 可维护性 > 优雅性
- 遵循项目现有风格与命名规范
- **注释要求详尽**，应说明意图、逻辑思路、约束条件、坑点与边界情况；避免重复代码本身显而易见的内容
- **中文注释要求（最高优先级）**：从本条规则生效起，后续新增或重构的核心业务代码，必须优先满足“未来任何新同学第一次读代码都能快速上手”的目标。具体要求如下：
  - **注释目标**：注释不是解释 Python 语法，而是解释“这段代码在平台里的职责、边界、关键约束、为什么这样设计”。
  - **优先级顺序**：`领域模型和 service 边界 > 数据结构 / 契约 / 状态机 > 复杂流程和关键分支 > 普通实现细节`。
  - **注释形式**：
    - 模块头注释、类注释、public 方法 docstring：**中文为主**，必要时保留少量固定英文术语（如 `FlowDraft`、`Run`、`Resolver`、`Executor`、`runtime`、`snapshot`）。
    - 关键代码块前的行注释：默认使用**简短结论式中文注释**。
    - 只有在逻辑特别复杂时，才升级为“设计原因 / 风险 / 约束”的结构化说明式注释。
  - **模型注释规则**：
    - 模型本身必须写中文职责说明。
    - **关键字段逐个解释**，尤其是宿主、版本、快照、状态、审核、风险、桥接相关字段。
    - 普通字段（如 `name`、`created_at`、`updated_at`）不做机械解释。
  - **Service 注释规则**：
    - public 方法必须写中文 docstring，说明它解决的业务动作、输入输出语义、是否改状态、是否落库、是否触发审核/快照/桥接。
    - private 方法只给关键逻辑写注释，尤其是：预检、桥接、版本锁定、事务边界、权限收缩、关键转换逻辑。
  - **明确禁止的注释**：
    - 逐行翻译代码。
    - 解释显而易见的赋值、返回、遍历。
    - 用空泛句式重复代码字面含义。
  - **适用范围**：
    - 该规则对 `datamakepool` 相关模型、service、bridge、resolver、executor、治理逻辑、关键 API skeleton 优先强制执行。
    - 若旧代码注释风格不满足本规则，不要求一次性全量补齐，但后续凡修改到关键模块，应顺手按本规则补齐或改善。
- 重复不足三次不急于抽象；避免"聪明技巧"牺牲可读性
- 先修复明确问题，再扩展能力；非必要不扩大改动范围
- 不兼容调整必须在交付时说明影响

---

## 语言规范

**简体中文沟通**：交流对话过程中，所有思考、分析、解释和回答必须使用简体中文。