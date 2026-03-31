<div align="center">

![Xagent Banner](./assets/github_readme_banner.jpg)

[![Discord](https://img.shields.io/discord/1474756736358289609?style=for-the-badge&logo=discord)](https://discord.gg/R7TDFMzuXq)
[![Telegram](https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/+2_-SAVLtuJNkNWFl)
[![Twitter](https://img.shields.io/twitter/follow/xorbitsio?logo=x&style=for-the-badge)](https://twitter.com/xorbitsio)

[![Documentation](https://img.shields.io/badge/docs-docs.xagent.run-blue?style=for-the-badge&logo=gitbook)](https://docs.xagent.run/)
[![GitHub Release](https://img.shields.io/github/v/release/xorbitsai/xagent?logo=github&style=for-the-badge)](https://github.com/xorbitsai/xagent/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/xprobe/xagent-backend?style=for-the-badge&logo=docker)](https://hub.docker.com/r/xprobe/xagent-backend)

</div>

---

## Xagent 是什么？ / What is Xagent?

**描述任务，而非工作流。**

**Describe tasks. Not workflows.**

**不再需要流程图。**
**No more flowcharts.**

**不再需要僵化的自动化。**
**No more rigid automation.**

**只需告诉 Xagent 你想要什么。**
**Just tell Xagent what you want.**

👏 加入 [Telegram](https://t.me/+2_-SAVLtuJNkNWFl) | [Discord](https://discord.gg/R7TDFMzuXq)

❤️ 喜欢 Xagent？请给个 Star 🌟 支持开发！
❤️ Like Xagent? Give it a star 🌟 to support the development!

---

## Xagent vs OpenClaw

| 能力 | Xagent | OpenClaw |
| ---- | ------ | -------- |
| 核心设计 | **企业级智能体平台** | 自主个人智能体 |
| 安全性 | **虚拟机级沙箱**，安全执行智能体 | 仅 Docker 容器沙箱，实际使用常需提升主机权限 |
| 智能体架构 | **LLM 驱动规划 + 高效多智能体编排** | 主要是线性任务执行 |
| 模型能力 | **API 兼容* + 模型原生智能** | API 或本地模型仅作为简单插件使用（无深度集成） |
| 知识系统 | **企业 RAG / 知识平台** | 本地记忆 / 轻量级 RAG |
| 部署方式 | **灵活部署** — 本地、私有化（本地部署）或云端 | 主要是本地运行 |
| 多租户 | **租户感知架构** | 主要面向单用户 |

\* Xagent 同时支持 API 模型和开源模型，通过与 Xinference 深度集成实现模型级优化。

---

## 🎬 看看 Xagent 如何思考 / See Xagent Think

给它一个目标。
Give it a goal.

看着它规划、选择工具、执行并交付。
Watch it plan, select tools, execute, and deliver.

![Xagent Demo](./assets/task_demo.jpg)

---

## ⚡ 问题所在 / The Problem

**工作流构建器是僵化的。当需求变化时，它们就会崩溃。**
**Workflow builders are rigid. They break when requirements change.**

- 你需要手动映射每个决策分支
- You map every decision branch manually
- 你需要手动编排工具
- You orchestrate tools by hand
- 你需要维护脆弱的流程图
- You maintain fragile flow diagrams
- 当逻辑变化时，你需要重新设计
- You re-engineer when logic changes

---

## 🎯 Xagent 的方式 / The Xagent Way

**使用 Xagent，你只需描述结果——而非步骤。**
**With Xagent, you describe the outcome — not the steps.**

- 动态规划任务
- Plans the task dynamically
- 分解为可执行步骤
- Decomposes into executable steps
- 自动选择正确的工具
- Selects the right tools automatically
- 执行、评估并迭代
- Executes, evaluates, and iterates

---

## 🚀 你可以构建什么 / What You Can Build

使用 Xagent，你不需要设计工作流。你只需要描述任务。就这么简单。
With Xagent, you don't design workflows. You describe the task. That's it.

**只需定义你想要完成什么——Xagent 会规划、分解、选择工具并执行。**
**Just define what you want done — and Xagent plans, decomposes, selects tools, and executes.**

### 你可以构建任何能描述的内容：

| 领域 | 示例 |
| ---- | ---- |
| **内容创作** | 自动生成 PPT、营销海报、创意设计素材 |
| **研究与分析** | 深度分析报告、研究摘要、数据综合 |
| **企业自动化** | 内部团队 AI 副驾驶、知识助手、任务自动化 |
| **商业智能** | 数据报表自动化、SaaS 功能、多步推理系统 |
| **知识工作** | 文档处理、信息提取、结构化输出 |

**如果你能清晰描述目标，Xagent 就能将其转化为可执行系统。**
**If you can clearly describe the goal, Xagent can turn it into an executable system.**

所有这些都由一个统一的运行时驱动。
All powered by one unified runtime.

---

## 🚀 快速开始 / Quick Start

**3 分钟上手**
**Get started in 3 minutes**

### 1️⃣ 克隆并配置 / Clone and configure

```bash
git clone https://github.com/xorbitsai/xagent.git
cd xagent
cp example.env .env
```

### 本地启动
python -m xagent.web --host 127.0.0.1 --port 8000 --reload --debug

### 2️⃣ 使用 Docker 启动 / Start with Docker

```bash
docker compose up -d
```

启用沙箱（需要 Linux 或支持 KVM 的 WSL2）：
To enable sandbox (requires Linux or WSL2 with KVM support):

```bash
docker compose -f docker-compose-sandbox.yml up -d
```

### 3️⃣ 打开浏览器 / Open in browser

```
http://localhost:80
```

首次启动时，Xagent 会重定向到 `/setup`。
On first startup, Xagent redirects to `/setup`.

在那里创建第一个管理员账户以完成初始化。
Create the first administrator account there to complete initialization.

如果忘记管理员密码，可通过 CLI 重置：
If the admin password is forgotten, reset it via CLI:

```bash
python -m xagent.web.reset_admin_password --username <admin_username>
```

就这样。Xagent 现在已经运行了。
That's it. Xagent is now running.

---

## ✨ 核心功能 / Core Features

### 🧠 动态规划引擎 / Dynamic Planning Engine

与传统工作流工具不同，Xagent 在运行时动态规划任务。
Unlike traditional workflow tools, Xagent plans tasks dynamically at runtime.

- 自动任务分解
- Automatic task decomposition
- 规划 → 执行 → 反思循环
- Plan → Execute → Reflect loops
- 条件分支
- Conditional branching
- 多步推理
- Multi-step reasoning

**没有静态流程。没有脆弱链条。**
**No static flows. No brittle chains.**

---

### 🔌 工具与模型编排 / Tool & Model Orchestration

Xagent 连接你的整个技术栈：
Xagent connects to your entire stack:

- OpenAI、Anthropic 和其他 LLM 提供商
- OpenAI, Anthropic and other LLM providers
- 通过 Xinference 托管的本地模型
- Self-hosted models via Xinference
- 外部 API
- External APIs
- 知识库（RAG）
- Knowledge bases (RAG)
- 内部企业系统
- Internal enterprise systems

它在执行过程中自动选择和编排工具。
It selects and orchestrates tools automatically during execution.

---

### ⚡ 即时执行模式 / Instant Execution Mode

对于简单用例，即时运行支持工具的 LLM 调用。
For simple use cases, run tool-enabled LLM calls instantly.

- 无配置开销
- No configuration overhead
- 聊天式助手
- Chat-style assistants
- 嵌入式 AI 功能
- Embedded AI features

**从简单开始。需要时再扩展。**
**Start simple. Scale when needed.**

---

### 📊 可观测性与控制 / Observability & Control

为真实生产环境打造：
Built for real production use:

- 任务生命周期追踪
- Task lifecycle tracking
- Token 使用监控
- Token usage monitoring
- 执行状态管理
- Execution state management
- 多用户支持
- Multi-user support

**像真实系统一样运营智能体——而非演示。**
**Operate agents like real systems — not demos.**

---

## 🎬 Xagent 实战 / Xagent in Action

观看 Xagent 实时规划、执行和交付结果。
Watch Xagent plan, execute, and deliver results in real-time.

![Xagent in Action](./assets/task.gif)

---

## 保持领先 / Stay Ahead

Xagent 正在积极开发中，快速演进。
Xagent is actively developed and rapidly evolving.

![Stay Ahead](./assets/xagent_stay_ahead.gif)

**关注我们的进展：**
**Follow our progress:**
- ⭐ 在 GitHub 上给我们 Star 以获取更新
- ⭐ Star us on GitHub to stay updated
- 🐛 报告问题和请求功能
- 🐛 Report issues and request features
- 💬 加入我们的社区讨论
- 💬 Join our community discussions

---

## 🏢 部署选项 / Deployment Options

Xagent 支持：
Xagent supports:

- 自托管部署
- Self-hosted deployment
- 私有云环境
- Private cloud environments
- 本地企业基础设施
- On-premise enterprise infrastructure
- 基于 Docker 的部署
- Docker-based setup

**你掌控你的模型、数据和基础设施。**
**You control your models, data, and infrastructure.**

---

## 🏗 架构概览 / Architecture Overview

Xagent 分离核心职责：
Xagent separates core responsibilities:

| 层级 | 职责 |
| ---- | ---- |
| **智能体定义** | 意图与约束 |
| **规划引擎** | 动态分解 |
| **执行运行时** | 编排层 |
| **工具层** | 集成与操作 |
| **模型层** | LLM 与推理后端 |

**此架构支持：**
**This architecture enables:**
- 复杂推理下的稳定性
- Stability under complex reasoning
- 安全迭代
- Safe iteration
- 水平可扩展性
- Horizontal scalability
- 长期可维护性
- Long-term maintainability

---

## 🔍 不是工作流构建器 / Not a Workflow Builder

**Xagent 不是：**
**Xagent is not:**
- 拖拽式流程编辑器
- A drag-and-drop flow editor
- 静态模板引擎
- A static template engine
- 聊天机器人包装器
- A chatbot wrapper

**Xagent 是：**
**Xagent is:**
- 动态任务执行引擎
- A dynamic task execution engine
- 自主规划系统
- An autonomous planning system
- 构建真实 AI 智能体的基础
- A foundation for building real AI agents

---

## 🤝 贡献 / Contributing

我们欢迎开发者、产品构建者和研究人员。
We welcome developers, product builders, and researchers.

提交 Issue。提交 PR。共同塑造 AI 智能体的未来。
Open issues. Submit PRs. Help shape the future of AI agents.

---

## 💬 社区与联系 / Community & Contact

**[文档 / Documentation](https://docs.xagent.run/)** - 完整文档和指南
**[GitHub Issues](https://github.com/xorbitsai/xagent/issues)** - 报告 Bug 或提出功能建议
**[Discord](https://discord.gg/R7TDFMzuXq)** - 分享你的任务或智能体，与社区交流
**[Telegram](https://t.me/+2_-SAVLtuJNkNWFl)** - 加入我们的 Telegram 群组进行讨论
**[X (Twitter)](https://twitter.com/xorbitsio)** - 关注获取更新并分享你的作品

---

## 📄 许可证 / License

本项目基于 Xagent Source License 许可 - 详情请参见 [LICENSE](LICENSE) 文件。
This project is licensed under the Xagent Source License - see the [LICENSE](LICENSE) file for details.