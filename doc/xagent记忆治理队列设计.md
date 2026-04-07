# XAgent 记忆治理任务队列设计

## 1. 已确认设计决策

- 队列类型：`Database-backed queue`
- worker 运行方式：`Separate worker process`
- 不引入 Redis / Celery / 外部消息中间件
- 先复用现有数据库、FastAPI 体系和独立后台进程模式

## 2. 推荐总体方案

采用 `Typed Job Queue + Executor Registry`。

核心组成：

- `memory_jobs`：数据库任务表
- `MemoryJobManager`：业务侧 enqueue 入口
- `MemoryGovernanceWorker`：独立进程，负责轮询、抢占、执行、回写状态
- `MemoryJobExecutorRegistry`：按 `job_type` 分发 executor
- `ExtractMemoriesExecutor`：提炼 durable / experience
- `ConsolidateMemoriesExecutor`：去重、合并、刷新 freshness
- `ExpireMemoriesExecutor`：过期治理、标记 stale / expired

第一版只要求两条主链路跑通：

- React / DAG 完成后 enqueue `extract_memories`
- worker 周期性 enqueue 并执行 `consolidate_memories` / `expire_memories`

## 3. 数据表设计

新增表：`memory_jobs`

建议字段：

- `id`：主键
- `job_type`：任务类型
- `status`：任务状态
- `priority`：优先级
- `payload_json`：任务输入
- `dedupe_key`：任务去重键
- `source_task_id`：来源任务 ID
- `source_session_id`：来源会话 ID
- `source_user_id`：来源用户 ID
- `source_project_id`：来源项目 ID
- `attempt_count`：已重试次数
- `max_attempts`：最大重试次数，默认 `3`
- `available_at`：最早可执行时间
- `lease_until`：任务租约到期时间
- `locked_by`：抢到任务的 worker ID
- `last_error`：最后一次错误
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`

`job_type` 第一版先支持：

- `extract_memories`
- `consolidate_memories`
- `expire_memories`

`status` 第一版先支持：

- `pending`
- `running`
- `succeeded`
- `failed`
- `dead`
- `cancelled`

建议索引：

- `(status, available_at)`
- `(job_type, status, available_at)`
- `(dedupe_key, status)`
- `(source_user_id, source_session_id, created_at)`
- `(lease_until)`

建议约束：

- `status` 用受限字符串或 enum
- `attempt_count <= max_attempts`
- `dedupe_key` 不做全局唯一
- enqueue 时只检查 `pending/running` 的同 key 任务

## 4. Payload 设计

### 4.1 `extract_memories`

作用：

- 从一次 agent 完成结果里提炼 durable / experience 候选

建议 `payload_json`：

- `task`
- `result`
- `classification`
- `session_id`
- `user_id`
- `project_id`
- `task_id`
- `pattern`：`react` / `dag`

推荐 `dedupe_key`：

- `extract:{task_id}`

### 4.2 `consolidate_memories`

作用：

- 扫描某范围记忆，做 dedupe / freshness 刷新 / stale 预处理

建议 `payload_json`：

- `memory_type`
- `user_id`
- `project_id`
- `scope`
- `limit`
- `older_than`
- `batch_key`

### 4.3 `expire_memories`

作用：

- 找出过期或过旧记忆并标记状态

建议 `payload_json`：

- `memory_type`
- `user_id`
- `project_id`
- `before_time`

## 5. Worker 生命周期

建议启动入口：

```bash
python -m xagent.worker.memory_governance
```

worker 主循环：

1. `poll`：查可执行任务
2. `claim`：原子抢占任务
3. `execute`：按 `job_type` 分发 executor
4. `finalize`：成功或失败后更新状态

抢任务条件：

- `status='pending'`
- `available_at <= now`
- `lease_until is null or lease_until < now`

抢到后更新：

- `status='running'`
- `locked_by=<worker_id>`
- `lease_until=now + lease_seconds`
- `started_at=now`

成功后更新：

- `status='succeeded'`
- `finished_at=now`
- `lease_until=null`
- `locked_by=null`
- `last_error=null`

失败后处理：

- `attempt_count += 1`
- 若未超过上限：重新置为 `pending` 并退避
- 若超过上限：置为 `dead`

建议退避：

- 第 1 次失败：30 秒
- 第 2 次失败：2 分钟
- 第 3 次失败：10 分钟

崩溃恢复依赖 `lease_until`：

- `running` 且 `lease_until < now` 的任务应允许重新 claim

## 6. Enqueue 策略

### 6.1 请求完成后入队

触发点：

- React 完成后
- DAG 完成后

动作：

- enqueue `extract_memories`

### 6.2 维护型入队

由独立 worker 内的 maintenance scheduler 周期检查：

- `consolidate_memories`：每 10 到 30 分钟检查一次
- `expire_memories`：每 1 到 6 小时检查一次

推荐 `dedupe_key`：

- `consolidate:{user_id or global}:{memory_type}:{time_bucket}`
- `expire:{user_id or global}:{memory_type}:{time_bucket}`

### 6.3 手动入队

后续可以补内部 API 或 admin 命令：

- 手动触发某个 session 的 `extract_memories`
- 手动触发某个用户 / 项目的 `consolidate_memories`
- 手动触发全局 `expire_memories`

## 7. 文件拆分建议

### 7.1 数据库层

- `src/xagent/web/models/memory_job.py`
- `alembic/versions/<timestamp>_add_memory_jobs_table.py`

### 7.2 队列管理层

- `src/xagent/core/memory/job_types.py`
- `src/xagent/core/memory/job_repository.py`
- `src/xagent/core/memory/job_manager.py`

### 7.3 执行器层

- `src/xagent/core/memory/job_executors/base.py`
- `src/xagent/core/memory/job_executors/extract_memories.py`
- `src/xagent/core/memory/job_executors/consolidate_memories.py`
- `src/xagent/core/memory/job_executors/expire_memories.py`
- `src/xagent/core/memory/job_executor_registry.py`

### 7.4 worker 层

- `src/xagent/worker/memory_governance.py`
- `src/xagent/worker/maintenance_scheduler.py`
- 可选：`src/xagent/worker/__main__.py`

### 7.5 接入点

- `src/xagent/core/agent/pattern/react.py`
- `src/xagent/core/agent/pattern/dag_plan_execute/dag_plan_execute.py`

## 8. 按 commit 拆分的实施顺序

### Wave 1

1. 新增 `memory_jobs` 表
2. 新增 `job_types.py` + `job_repository.py`
3. 新增 `job_manager.py`

### Wave 2

4. 新增 `extract_memories` executor
5. 新增 worker 主循环
6. React 改为 enqueue `extract_memories`
7. DAG 改为 enqueue `extract_memories`

### Wave 3

8. 新增 `consolidate_memories` executor
9. 新增 `expire_memories` executor
10. 新增 maintenance scheduler
11. 补齐 job / worker / enqueue 回归测试

## 9. 第一版边界

第一版必须做到：

- React / DAG 完成后写 `extract_memories` job
- 独立 worker 能消费 job
- durable / experience 能经由 worker 落库
- consolidation / expire 能由 scheduler 周期发 job

第一版先不做：

- 前端任务管理页面
- 复杂批量并发控制
- heartbeat 续租
- 人工重放按钮
- 分布式 leader election

## 10. 推荐路线

建议直接按：

- `Wave 1 -> Wave 2 -> 验证 -> Wave 3`

不要把 `consolidate` / `expire` 一开始就和 queue 基础设施一起上线，否则出问题时很难定位是：

- job 表设计
- claim/retry
- executor
- maintenance scheduler

先把 `extract_memories` 跑通，再补治理任务，会稳很多。

## 11. 当前实现状态

截至当前代码状态，`Wave 1 ~ Wave 3` 已完成：

- 已有 `memory_jobs` 表、repository、manager、retry/backoff
- React / DAG 已从同步 extractor 改成 enqueue `extract_memories`
- 已有 `ExtractMemoriesExecutor`
- 已有独立 worker：`python -m xagent.worker.memory_governance`
- 已有 `ConsolidateMemoriesExecutor`
- 已有 `ExpireMemoriesExecutor`
- 已有 `MemoryMaintenanceScheduler`
- worker 默认启动时会调度 `durable` / `experience` 的 consolidate / expire 任务

当前第一版治理语义如下：

- `extract_memories`
  - 从一次任务结果中提炼 durable / experience 候选
  - 由 worker 异步落库
- `consolidate_memories`
  - 按 `dedupe_key` 合并重复记忆
  - 保留最新主记录，合并 `freshness_at` / `importance` / `confidence`
  - 删除重复记录
- `expire_memories`
  - 基于 `before_time` 或 `expires_at` 标记 `expired`
  - 同时写入 `freshness_label`
  - `stale` 目前保留 `status=active`，只通过 `freshness_label=stale` 表达

当前配套行为：

- `MemoryRetriever` 默认只召回 `status=active` 的记忆
- 因此 `expired` 记忆不会继续进入 prompt 检索链路
- API / store filter 已支持 `project_id`、`source_session_id`、`dedupe_key`、`status`

## 12. 当前启动方式

后台 worker：

```bash
python -m xagent.worker.memory_governance
```

单次消费一个循环：

```bash
python -m xagent.worker.memory_governance --once
```

只消费指定 job type：

```bash
python -m xagent.worker.memory_governance --job-type extract_memories
python -m xagent.worker.memory_governance --job-type consolidate_memories
python -m xagent.worker.memory_governance --job-type expire_memories
```

说明：

- 不传 `--job-type` 时，worker 会启用 maintenance scheduler
- 传了 `--job-type` 时，当前实现不会自动启动 scheduler，只消费指定类型任务

## 13. 下一步建议

下一阶段优先做下面两件事：

- 增加 memory job 的管理 / 观察 API
  - 例如：任务列表、失败任务、dead job 重试
- 把治理策略参数化
  - 例如：不同 `memory_type` 的 stale / expire 阈值进入配置，而不是先写死在 scheduler 里

## 14. 已实现的 Job 管理 API

当前后端已经补了最小可用的 memory job 管理接口：

- `GET /api/memory/jobs`
  - 支持按 `job_type`
  - 支持按 `status`
  - 支持按 `source_task_id`
  - 支持按 `source_session_id`
  - 支持按 `source_project_id`
- `GET /api/memory/jobs/{job_id}`
- `POST /api/memory/jobs/{job_id}/retry`

当前 retry 规则：

- 只允许重试 `failed` / `dead` / `cancelled`
- retry 后会：
  - 重置为 `pending`
  - `attempt_count = 0`
  - 清空 `locked_by`
  - 清空 `lease_until`
  - 清空 `last_error`

权限策略：

- admin 可查看全部 memory jobs
- 普通用户当前只可查看自己的 memory jobs

这套 API 已足够支撑下一步前端治理面板或简单 admin 页面。
