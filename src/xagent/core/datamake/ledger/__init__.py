"""
`Memory / Ledger Plane`（记忆 / 账本平面）。

这层对应你设计里的“事实留痕层”。
它保存的不是随手写的日志，而是能支撑恢复、审计、诊断、投影查询的
结构化业务事实。

核心原则：
- `Ledger`（业务账本）是事实源，不是主脑。
- `Projection`（投影）是为了查询方便而生成的派生视图。
- `Replay`（回放）和 `Snapshot`（快照）是为恢复与调试服务。
"""

from .http_trace_builder import HttpExecutionTraceBuilder

__all__ = [
    "HttpExecutionTraceBuilder",
]
