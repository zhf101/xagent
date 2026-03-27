"""统一 Recall Funnel Framework。"""

from .executor import RecallFunnelExecutor
from .protocol import (
    RecallAdapter,
    RecallCandidate,
    RecallExecutionResult,
    RecallQuery,
    RecallStageResult,
)
from .utils import load_default_embedding_adapter

__all__ = [
    "RecallAdapter",
    "RecallCandidate",
    "RecallExecutionResult",
    "RecallFunnelExecutor",
    "RecallQuery",
    "RecallStageResult",
    "load_default_embedding_adapter",
]
