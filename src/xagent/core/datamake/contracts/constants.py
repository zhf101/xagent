"""
`Constants`（常量定义）模块。

这里集中定义 datamake 各模块使用的字符串常量，避免硬编码散落在各处。
所有常量都使用 Literal 类型，便于类型检查和 IDE 自动补全。
"""

from typing import Literal

# =============================================================================
# 决策相关常量（NextActionDecision）
# =============================================================================

# 决策模式 - 决定当前轮是继续动作分发还是直接终止
DECISION_MODE_ACTION: Literal["action"] = "action"
"""动作模式 - 表示进入正常动作分发，继续走 interaction/execution/supervision 路径"""

DECISION_MODE_TERMINATE: Literal["terminate"] = "terminate"
"""终止模式 - 表示任务已完成或无法继续，直接返回最终结果，不进入动作分发"""

# 动作类别 - 只在 decision_mode=action 时有效
ACTION_KIND_INTERACTION: Literal["interaction_action"] = "interaction_action"
"""交互动作 - 需要与用户交互澄清，如 ask_clarification（请求澄清）"""

ACTION_KIND_SUPERVISION: Literal["supervision_action"] = "supervision_action"
"""监督动作 - 需要人工监督或审批，如 request_human_confirm（请求人工确认）"""

ACTION_KIND_EXECUTION: Literal["execution_action"] = "execution_action"
"""执行动作 - 需要执行具体操作，如 execute_registered_action（执行注册动作）"""

# =============================================================================
# 分发结果类别常量（DispatchOutcome.kind）
# =============================================================================

DISPATCH_KIND_FINAL: Literal["final"] = "final"
"""最终结果 - 任务已完成，返回最终结论给用户"""

DISPATCH_KIND_OBSERVATION: Literal["observation"] = "observation"
"""观察结果 - 动作已执行完毕，产生观察结果回流给 Agent 重新决策"""

DISPATCH_KIND_WAITING_USER: Literal["waiting_user"] = "waiting_user"
"""等待用户 - 当前轮已进入等待用户回复状态，需要用户输入后继续"""

DISPATCH_KIND_WAITING_HUMAN: Literal["waiting_human"] = "waiting_human"
"""等待人工 - 当前轮已进入等待人工审批状态，需要人工确认后继续"""

# =============================================================================
# Guard 评估结果类别常量（GuardEvaluationResult.kind）
# =============================================================================

GUARD_RESULT_KIND_OBSERVATION: Literal["observation"] = "observation"
"""观察结果 - Guard 已完成评估，直接产生观察结果（可能是 blocker 或执行结果）"""

GUARD_RESULT_KIND_APPROVAL_REQUIRED: Literal["approval_required"] = "approval_required"
"""需要审批 - 当前动作需要人工审批，应转入 supervision 通道"""

# =============================================================================
# 执行模式常量（CompiledExecutionContract.mode）
# =============================================================================

EXECUTION_MODE_PROBE: Literal["probe"] = "probe"
"""探测模式 - 只做无副作用的校验和预览，不执行真实写入/删除操作"""

EXECUTION_MODE_EXECUTE: Literal["execute"] = "execute"
"""正式模式 - 执行真实操作，会产生实际副作用"""

# =============================================================================
# 路由常量（GuardVerdict.route）
# =============================================================================

ROUTE_RUNTIME_PROBE: Literal["runtime_probe"] = "runtime_probe"
"""探测路由 - 动作应走 ProbeExecutor 执行"""

ROUTE_RUNTIME_EXECUTE: Literal["runtime_execute"] = "runtime_execute"
"""正式路由 - 动作应走 ActionExecutor 执行"""

# =============================================================================
# 运行时状态常量（RuntimeResult.status）
# =============================================================================

RUNTIME_STATUS_SUCCESS: Literal["success"] = "success"
"""执行成功 - 技术执行层面成功完成"""

RUNTIME_STATUS_FAILED: Literal["failed"] = "failed"
"""执行失败 - 技术执行层面失败（如网络异常、协议错误）"""

RUNTIME_STATUS_PAUSED: Literal["paused"] = "paused"
"""执行暂停 - 执行过程中被暂停，等待恢复"""

# =============================================================================
# 资源适配器类型常量（ResourceActionDefinition.adapter_kind）
# =============================================================================

ADAPTER_KIND_SQL: Literal["sql"] = "sql"
"""SQL 适配器 - 用于执行 SQL 数据库操作"""

ADAPTER_KIND_HTTP: Literal["http"] = "http"
"""HTTP 适配器 - 用于执行 HTTP API 调用"""

# =============================================================================
# 观察结果类型常量（ObservationEnvelope.observation_type）
# =============================================================================

OBSERVATION_TYPE_INTERACTION: Literal["interaction"] = "interaction"
"""交互观察 - 用户交互结果"""

OBSERVATION_TYPE_SUPERVISION: Literal["supervision"] = "supervision"
"""监督观察 - 人工监督结果"""

OBSERVATION_TYPE_EXECUTION: Literal["execution"] = "execution"
"""执行观察 - 执行成功结果"""

OBSERVATION_TYPE_FAILURE: Literal["failure"] = "failure"
"""失败观察 - 执行失败结果"""

OBSERVATION_TYPE_BLOCKER: Literal["blocker"] = "blocker"
"""阻断观察 - 执行被 Guard 阻断"""

OBSERVATION_TYPE_PAUSE: Literal["pause"] = "pause"
"""暂停观察 - 执行暂停结果"""

# =============================================================================
# 观察结果状态常量（ObservationEnvelope.status）
# =============================================================================

OBSERVATION_STATUS_SUCCESS: Literal["success"] = "success"
"""成功 - 操作成功完成"""

OBSERVATION_STATUS_FAIL: Literal["fail"] = "fail"
"""失败 - 操作失败"""

OBSERVATION_STATUS_PENDING: Literal["pending"] = "pending"
"""等待中 - 操作等待执行"""

OBSERVATION_STATUS_CONFIRMED: Literal["confirmed"] = "confirmed"
"""已确认 - 用户或人工已确认"""

OBSERVATION_STATUS_BLOCKED: Literal["blocked"] = "blocked"
"""被阻断 - 操作被 Guard 阻断"""

OBSERVATION_STATUS_PAUSED: Literal["paused"] = "paused"
"""已暂停 - 操作已暂停"""

# =============================================================================
# 协议状态常量（用于 normalizer，表示 HTTP 协议层状态）
# =============================================================================

PROTOCOL_STATUS_SUCCESS: Literal["success"] = "success"
"""协议层成功 - HTTP 状态码在成功范围内（如 200-299）"""

PROTOCOL_STATUS_FAILED: Literal["failed"] = "failed"
"""协议层失败 - HTTP 状态码不在成功范围内"""

# =============================================================================
# 业务状态常量（用于 normalizer，表示业务层状态）
# =============================================================================

BUSINESS_STATUS_SUCCESS: Literal["success"] = "success"
"""业务层成功 - 业务逻辑返回成功"""

BUSINESS_STATUS_FAILED: Literal["failed"] = "failed"
"""业务层失败 - 业务逻辑返回失败"""

# =============================================================================
# 结果归一化器类型常量（ResourceActionDefinition.result_normalizer）
# =============================================================================

NORMALIZER_HTTP_STRUCTURED: Literal["http_structured"] = "http_structured"
"""结构化 HTTP 归一化器 - 拆分传输/协议/业务三层状态"""

NORMALIZER_PASSTHROUGH: Literal["passthrough"] = "passthrough"
"""透传归一化器 - 直接透传原始结果，不做额外解析"""