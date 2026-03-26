# Xagent Agent System

Xagent is a powerful and flexible framework for building and running AI-powered agents with support for various execution patterns, tools, memory management, and observability.

## Features

- **Agent Patterns**: ReAct, DAG plan-execute
- **Nested Agents**: Hierarchical agent execution with parent-child relationships
- **Tool System**: Built-in tools with auto-discovery mechanism
- **Memory Management**: LanceDB-based vector storage with semantic search
- **Observability**: Langfuse integration for tracing and monitoring
- **Real-time Communication**: WebSocket support for agent execution monitoring



## 0. 总原则

- **质量第一**：代码质量和系统安全不可妥协。
- **思考先行**：编码前必须深度分析和规划。
- **以交付为导向**：推动需求变成可验证、可运行的结果。
- **证据优先**：关键判断基于代码、配置、日志、文档、命令输出，不基于推测。
- **先做对，再做漂亮**；先可验证，再谈扩展性。
- **能解决真实问题，就不增加无效动作**。
- 如与用户明确要求冲突，以用户要求为准。
- **输出精简聚焦**：执行类任务的过程更新只说进展，不解释推导。但**如果任务性质是纯分析、咨询、代码审查或方案设计，应使用正常的 Markdown 充分展开论述，此时不受极简和折叠限制**，务必保证解释透彻、让人大彻大悟。
- **分析类回答的结构**：回答咨询、对比、方案类问题时，优先按三层递进组织内容：
  1. **先给结论**：简明扼要地直接回答用户的核心问题
  2. **再展全貌**：用表格或对比列表展示能力边界、可选方案、优劣对比等
  3. **最后给操作步骤**：用表格或编号步骤说明具体怎么做、下一步是什么
  - 简单问答无需强套此结构，视内容复杂度灵活运用
- 所有文档与代码默认 UTF-8（无 BOM）编码。
- 所有面向用户的输出（进度、计划、交付说明、风险提示）**必须使用中文**。
- 如项目子目录存在更近层级的 `AGENTS.md`，优先遵循更近层级规则。

---

## 1. 执行纪律（最高优先级）

> 以下三条规则优先级高于其他所有流程规定。违反即为行为缺陷。

- **需求不清必须先确认**：存在歧义或多种理解时，必须先提问确认，不得自行假设后直接执行。宁可多确认一次，不可做错后返工。
- **按歧义和风险决定是否等确认**：需求清晰且低风险→回显理解后直接执行；需求有歧义或操作高风险→必须等用户明确表态（"可以了""开始做""去改"等）后才可实施。分析/评审/方案类任务始终只做读取和分析，不修改文件。
- **进度实时可见且使用中文**：除单文件微调外，所有任务必须显示结构化进度面板（见 §4），阶段切换时及时更新。

---

## 2. 需求澄清门

任何实质性执行开始前，代理必须先给一句任务理解，再列执行清单（通常 3–6 步，极小任务可压缩为 1–3 步）。

开场示例：
```text
【任务】为 XX 项目添加用户登录功能

【进度】1/5
- ✅ 确认需求理解
- ○ 确认技术方案
- ○ 实现登录控制器与视图
- ○ 添加 Session 中间件
- ○ 验证关键路径
- ⚠️ 风险：无
```

如有待确认点，用结构化提问（见下方格式）一次性问清后再执行。

执行判定：
- 低歧义任务：回显理解后可直接执行
- 中等歧义任务：回显理解 + 结构化提问，确认后再执行
- 高歧义任务：先提炼问题，**不得直接实施**

### 提问格式

需要确认时，每次最多 3 个关键问题，区分选择题和填空题：

```text
[1] 用户表结构（请说明）
当前用户表名和关键字段是什么？

[2] 登录页设计（选择）
- 2A. 我提供设计稿
- 2B. 你来设计（推荐）
```

用户可简短回复，如：`1: user表有username和password, 2B`

---

## 3. 任务分级

| 级别 | 适用场景 | 流程要求 | 留痕要求 |
|------|---------|---------|---------|
| **L0** | Bug 修复、文案/样式/配置微调、单文件改动 | 直接执行并验证 | 交付时说明改动与结果 |
| **L1** | 多文件联动、中等功能开发、局部重构 | 最小上下文收集 + 明确步骤 + 验证 | 记录必要决策和验证结论 |
| **L2** | 跨模块改动、新模块、数据库/权限/核心流程调整 | 完整闭环：澄清→方案→确认→实施→验证→交付 | 记录关键决策、风险、验证结果、部署/回滚事项 |

---

## 4. 工作流

| 阶段 | 目标 | 关键动作 |
|------|------|---------|
| **A. 上下文收集** | 获得足够推进交付的信息 | 定位相关文件/模块/配置；理解现有实现；找相似参照；识别关键疑问 |
| **B. 方案规划** | 把需求变成可执行方案 | 覆盖：功能拆解、接口/数据流、数据模型、异常处理、测试方案、部署影响。**有歧义或高风险时须等用户确认后再实施** |
| **C. 实施** | 按确认方案落地 | 小步修改可验证；先读后改沿用现有模式；优先复用已有模块 |
| **D. 验证** | 证明交付物可信 | 按风险选择验证方式（见 §8）；连续 3 次同类失败暂停重评 |
| **E. 交付** | 说明结果与风险 | 完成了什么、改了什么、验证了什么、还有什么风险（格式见下方示例） |

交付示例：
```text
【进度】5/5 ✅
- ✅ 确认技术方案
- ✅ 实现登录控制器与视图
- ✅ 添加路由配置
- ✅ 添加 Session 中间件
- ✅ 验证关键路径

交付摘要：
- 完成内容：用户登录功能（页面+验证+Session+中间件）
- 关键改动：新增 Login.php、login.html、Auth.php，修改 route/app.php
- 验证结果：正确登录/错误密码/未登录拦截 3 条路径通过
- 风险与限制：未实现登录失败次数限制
```

### 极简进度面板

**展示时机**：接到执行类任务后（写代码、排错、多步修改）。纯问答、分析、讨论类任务**无需**强制套用此面板。

每次过程更新使用以下固定格式，不展开长篇分析：

```text
【进度】2/5
- ✅ 已完成项
- ⏳ 进行中项
- ○ 待开始项
- ○ 待开始项
- ○ 待开始项
- ⚠️ 风险：无
```

要求：
- 内容必须中文，让用户一眼知道做到哪一步
- 除非用户要求，不重复背景，不输出大段论证
- 阶段有变化、出现阻塞或风险时及时更新

---

## 5. 按领域的执行要求

### 5.1 需求整理
- 先明确目标、范围、优先级，再进入实现
- 发现需求不一致、缺验收标准、边界不清时主动指出
- 复杂功能应拆成子任务或阶段性交付

### 5.2 UI / 前端
- **先保证信息结构与交互逻辑清晰，再考虑视觉细节**（覆盖系统默认的"视觉优先"倾向）
- 页面状态完整：加载、空态、错误、成功反馈不可忽略
- 组件命名、状态管理、路由逻辑符合项目现有模式
- 不为炫技引入过度抽象

### 5.3 后端 / 服务层
- 接口定义清晰：输入、输出、错误码、边界条件
- 优先保证业务正确性、幂等性、校验与异常处理
- 关注日志与排障可读性
- 避免"接口可写但不可用"的半成品交付

### 5.4 数据库 / 数据模型
- 修改前先明确读写路径、索引、约束与兼容性影响
- 迁移优先考虑安全性、回滚与历史数据兼容
- 破坏性 Schema 变更需用户确认

### 5.5 测试
- 测试服务于当前改动的主要风险
- 逻辑改动优先单测；接口改动优先集成验证；页面改动优先关键路径验证

### 5.6 部署与发布
- 必须识别：环境变量、构建/启动命令、数据迁移、外部依赖、权限/域名配置是否变化
- 给出最小可执行发布步骤
- 有风险时同时给出回滚思路

---

## 6. 编码原则

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

## 7. 测试与质量策略

- 验证与交付风险匹配，测试重点是发现问题，不是走仪式
- 建议验证组合：

| 改动类型 | 验证方式 |
|---------|---------|
| 纯逻辑修改 | 单元测试 + 类型检查 |
| 接口/服务层 | 接口测试 / 集成测试 + 冒烟验证 |
| 前端交互 | 构建检查 + 关键路径验证 |
| 数据库变更 | 迁移验证 + 读写验证 + 回滚评估 |
| 配置/构建 | 构建/启动验证 |

- 测试失败时必须说明：失败现象、复现方式、初步原因、下一步策略

---

## 8. 文档与留痕

- 文档服务于协作与维护，不为文档而文档
- 过程文档遵循最小化原则：只记录未来会忘但会有用的信息
- 留痕内容：关键取舍及原因、风险与限制、未完成项、验证结论
- 具体分级要求见 §3 任务分级表

---

## 9. 用户确认边界

**默认可直接执行**：
- 读取、检索、比较、总结
- 已通过需求澄清、且无需额外确认的低风险代码修改与文档更新
- 测试执行与构建验证
- 安装锁定依赖（`composer install`、`npm install` 等有 lock 文件的情况）
- 低风险 Git 操作：`status`、`diff`、`log`、`add`、`commit`

**必须先确认**：
- 删除核心文件
- 数据库 Schema 的破坏性变更
- 高风险 Git 操作：`push`、`rebase`、`reset`、`force` 系列
- 引入新依赖（`composer require`、`npm install <pkg>` 等）
- 涉及生产、真实数据、外部服务或付费资源的操作
- 显著改变范围、方案或交付形式的动作

判断原则：不在高风险清单且风险可控→直接执行；有疑问先评估再决定；避免低价值确认打断主线。

### 危险操作确认机制

执行以下操作前**必须获得明确确认**：

- **文件系统**：删除文件/目录、批量修改、移动系统文件
- **系统配置**：修改环境变量、系统设置、权限变更
- **数据操作**：数据库删除、结构变更、批量更新
- **网络请求**：发送敏感数据、调用生产环境 API
- **包管理**：全局安装/卸载、更新核心依赖

确认格式模板：

```
⚠️ 危险操作检测！

操作类型：[具体操作]
影响范围：[详细说明]
风险评估：[潜在后果]

请确认是否继续？[需要明确的 "是"、"确认"、"继续"]
```

---

## 10. 工具策略

- 工具是手段，优先"最低成本获得可靠结论"
- 本地工具足够时不强制调用 MCP；外部工具失败时优先降级不卡主线
- 降级后在交付说明中注明
- 引用工具/MCP 时必须是当前环境真实可用的，不引用未安装的工具

---

## 11. 行为准则

- **不猜**：不确定就说明不确定
- **不装**：没有验证就不假装已验证
- **不绕**：能直接完成就不把简单事做复杂
- **不僵**：规则服务于交付，不服务于形式
- **保持透明**：成功、失败、降级、风险都如实说明

---

## 12. 对话输出风格指南

> 沟通过程中，默认输出环境为终端，为了终端下文字阅读性更好，特别指定如下对话输出风格。

**核心原则**：使用**强视觉边界**（标题、分隔符）来组织内容。面向"技术+业务混合读者"，优先可读性，再保证技术准确性。

### 语言与语气

- **友好自然**：像专业朋友对话，避免生硬书面语，倾向于使用简洁、生动的短句
- **适度点缀**：在各类标题、要点、子列表前使用 🎯✨💡🔥⭐🩷⚠️🔍✅ 等 emoji 强化视觉引导
- **直击重点**：开篇用一句话概括核心思路（尤其对复杂问题）

### 内容组织与结构

- **标题（分组锚点）**：终端对话中优先使用 `**粗体**` 分组（可配 Emoji）；标题建议独占一行，并保留必要留白
- **要点清晰**：将长段落拆分为短句或条目，每点聚焦一个 idea
- **逻辑流畅**：多步骤任务用有序列表（1. 2. 3.）或者（1️⃣ 2️⃣ 3️⃣）
- **合理分隔**：不同信息块之间用 2 个空行分隔，创建清晰的"硬边界"
- **一图胜千言**：复杂流程优先用 ASCII 流程图/结构图，不用大段纯文字
- **短列表**：关键信息和对比项目等，优先用短列表，不写长段落
- **直观简洁**：句子短、口语化、避免术语堆叠；必要术语后给一句白话解释

> ❌ **反模式**：在终端中使用过于复杂或超长表格（尤其内容长、含代码或需连贯叙述时）

### 视觉与排版优化

- **简洁明了**：控制单行长度，适配终端宽度（建议 ≤80 字符）
- **适当留白**：合理使用空行，避免信息拥挤
- **重点突出**：关键信息用 `**粗体**` 或 `*斜体*` 强调

> ❌ **反模式**：滥用超长绝对路径
>
> **最佳实践**：追求简洁
> - 使用 `UserCore` 而不是 `com.xxx.module.UserCore`
> - 调试、评审、定位问题时，使用 `file:line` 提供可追溯定位信息，如：`UserCore:25`，避免写法`com.xxx.module.UserCore:25`

---

## 13. 技术内容规范

### 代码与数据展示

- **代码块**：多行代码、配置或日志务必用带语言标识的 Markdown 代码块
- **聚焦核心**：示例代码省略无关部分（如导入语句），突出关键逻辑
- **差异标记**：修改内容用 `+` / `-` 标注，便于快速识别变更
- **行号辅助**：必要时添加行号（如调试场景）

### 结构化数据与图示

**呈现优先级**：
1. **列表**：默认首选，适用于绝大多数场景
2. **表格**：仅用于需严格对齐的结构化数据（如参数对比、配置项）
3. **ASCII 图示**：当纯文本难以清晰表达结构/流程/层级关系时使用

### ASCII 图示使用规则

**适用场景**：
- 结构类：架构图、文件树、数据结构（树/图/链表）
- 流程类：状态机、时序图、流程图、生命周期
- 关系类：类图、ER 图、依赖关系、网络拓扑

**常用符号**：`├──`、`└──`、`│`、`→`、`┌┐└┘`、`[节点]`、`●`

---

## 14. 语言规范

**简体中文沟通**：交流对话过程中，所有思考、分析、解释和回答必须使用简体中文。

---

## 15. 何时更新本文件

- 协作中反复出现理解偏差后直接执行的问题
- 过程可见性不足，用户无法判断当前阶段
- 用户对确认边界、验证标准、交付方式提出新要求
- 本文件已明显影响效率，需简化或强化


## Architecture Overview

### Entry Points

Xagent has one main entrypoint:

**Web Interface (`src/xagent/web/`):**
- FastAPI-based web application with WebSocket support
- Real-time agent execution monitoring
- File upload and management
- DAG visualization
- API endpoints for agent operations

## Architecture Overview

### Core Components (`src/xagent/core/`)

**Agent System:**
- `agent.py` - Main Agent class with nested agent support and execution history
- `pattern/` - Agent execution patterns (ReAct, DAG plan-execute)
- `runner.py` - Agent execution engine
- `context.py` - Agent context management

**Graph System:**
- `graph.py` - Graph workflow execution engine with validation
- `node.py` - Node types (Start, End, Agent, Tool, etc.)
- `node_factory.py` - Node creation factory

**Tools System:**
- `adapters/` - Tool adapters for different frameworks
- `core/` - Core tool implementations (calculator, file operations, web search, etc.)
- Tool auto-discovery using `get_{tool_name}_tool()` naming convention

**Model Integration:**
- `llm/` - LLM provider implementations (OpenAI, Zhipu)
- Support for embedding models and reranking models

**Memory Management:**
- `storage/` - Storage manager and database operations
- `workspace.py` - Task workspace management with isolated working directories

**Observability:**
- Langfuse integration for tracing and monitoring
- Execution history and message tracking

### Available Tools

Xagent has two categories of tools:

**Basic Tools** (`src/xagent/core/tools/core/`):
- `calculator` - Mathematical expression evaluation
- `file_tool` - File operations (read, write, list, edit, delete)
- `workspace_file_tool` - Workspace file operations
- `python_executor` - Dynamic Python code execution
- `browser_use` - Browser automation
- `excel` - Excel file operations
- `document_parser` - Document parsing (PDF, DOCX, etc.)
- `image_tool` - Image processing

**Web & Search Tools** (`src/xagent/core/tools/core/`):
- `web_search` - Generic web search
- `image_web_search` - Image search functionality
- `zhipu_web_search` - Zhipu search integration
- `web_crawler` - Web crawling and content extraction

**RAG Tools** (`src/xagent/core/tools/core/RAG_tools/`):
- Document parsing and chunking
- Vector storage and retrieval (LanceDB)
- Knowledge base management
- Semantic search capabilities

**MCP Server Tools** (`src/xagent/core/tools/core/mcp/`):
- Model Context Protocol (MCP) server integration
- Standardized tool access via MCP protocol

**Skill Documentation Access Tools** (`src/xagent/core/tools/adapters/vibe/skill_tools.py`):
- `read_skill_doc` - Read documentation from skill directories (SKILL.md, examples, etc.)
- `list_skill_docs` - List documentation files in skill directories (returns names and sizes)
- `fetch_skill_file` - Copy resource files from skill directories to workspace

### Custom Tools

Create custom tools by adding Python files following the naming convention:

```python
from langchain_core.tools import BaseTool, tool

def get_my_tool(_info: Optional[dict[str, str]] = None) -> BaseTool:
    """My custom tool description"""
    return tool(my_tool_function)
```

**Requirements:**
- Function name pattern: `get_{tool_name}_tool()`
- File location: `src/xagent/core/tools/core/`
- Return type: `BaseTool` instance from langchain_core
- No manual registration needed - auto-discovery on load

## Environment Configuration

Create a `.env` file based on `example.env` with required API keys:
```bash
OPENAI_API_KEY="your-openai-key"
DEEPSEEK_API_KEY="your-deepseek-key"
GOOGLE_API_KEY="your-google-api-key"
GOOGLE_CSE_ID="your-google-cse-id"
LANGFUSE_PUBLIC_KEY="your-langfuse-public-key"
LANGFUSE_SECRET_KEY="your-langfuse-secret-key"
```

### Optional Dependencies for Presentation Generation

If you plan to use the presentation generator feature (JavaScript-based PowerPoint creation via `execute_javascript_code` tool), you need to install Node.js and pptxgenjs:

```bash
# Ensure Node.js 20+ is installed
node --version

# Install pptxgenjs globally for presentation generation
npm install -g pptxgenjs@4.0.1

# Verify installation
npm root -g  # Should show path to global node_modules
ls $(npm root -g)/pptxgenjs  # Should show the package directory
```

**Note:** Without this installation, the `javascript_executor` tool will fail with "Cannot find module 'pptxgenjs'" when generating presentations. The pptxgenjs package is automatically installed in Docker/CI environments.

## Development Commands

### Installation and Setup
```bash
# Install the package with core dependencies only (SQLite, basic PDF support)
pip install -e .

# Install development dependencies (requires pip >= 25.1 or uv)
pip install -e . --group dev

# Install optional extras for additional features
pip install -e ".[document-processing]" # Document processing libraries
pip install -e ".[ai-document]"         # AI-related document processing (docling)
pip install -e ".[postgresql]"          # PostgreSQL database driver
pip install -e ".[browser]"             # Browser automation (playwright)
pip install -e ".[chromadb]"            # ChromaDB vector database
pip install -e ".[milvus]"              # Milvus vector database
pip install -e ".[all]"                 # Install all optional extras

# For development with all features:
pip install -e ".[all]" --group dev

# For older pip versions, use uv instead:
# uv sync --group dev --extra all
```

**Optional Extras:**
| Extra | Description |
|-------|-------------|
| `document-processing` | document processing libraries (pdfplumber, unstructured, pymupdf, etc.) |
| `ai-document` | AI-related document processing (docling) |
| `postgresql` | PostgreSQL driver (uses psycopg2-binary; for production consider psycopg2) |
| `browser` | Browser automation (playwright) |
| `chromadb` | ChromaDB vector database (alternative to LanceDB) |
| `milvus` | Milvus vector database (alternative to LanceDB) |
| `all` | All optional extras combined |

**Note**: Pre-commit hooks are installed via `--group dev`, not as an optional extra.

### Running Tests
```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=src/xagent --cov-report=html

# Run specific test categories
pytest -m integration  # Integration tests
pytest -m slow         # Slow tests

# Run specific test files
pytest tests/core/agent/test_agent.py
pytest tests/web_integration/test_comprehensive.py
```

### Code Quality and Linting
```bash
# Format code with ruff
ruff format .

# Lint code with ruff
ruff check .

# Type checking with mypy
mypy src/xagent

# Run pre-commit hooks
pre-commit run --all-files
```

### Running the Application

Xagent has separate frontend and backend components:

**Backend (Web API):**
```bash
python -m xagent.web.__main__
# Runs on http://localhost:8000
```

**Frontend (Web UI):**
```bash
cd frontend
npm run dev    # Development mode with hot-reload
npm run build  # Production build
npm run start  # Production mode
# Frontend runs on http://localhost:3000
```

**Development Mode:**
Run both backend and frontend in separate terminals for full-stack development.

## Skills Configuration

Skills directories can be extended using the `XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS` environment variable:
- External directories are **appended** to default built-in and user directories
- Comma-separated list of paths
- Supports local directories, home directory expansion, and environment variables
- Non-existent paths are skipped with warnings
- Default directories are always loaded

Load order: built-in → user → external (later skills override earlier ones with the same name)

Examples:
```bash
# Single directory (appended to defaults)
XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS="/path/to/custom/skills"

# Multiple directories
XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS="/path/to/skills1,/path/to/skills2,~/skills"

# With path expansion
XAGENT_EXTERNAL_SKILLS_LIBRARY_DIRS="~/skills,$HOME/custom_skills,./local_skills"
```

See `src/xagent/skills/README.md` for details.
Run both backend and frontend in separate terminals for full-stack development.
