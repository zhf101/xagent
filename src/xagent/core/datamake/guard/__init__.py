"""
`Guard / Routing Plane`（护栏 / 路由平面）。

这一层是你设计里“执行前总闸门”所在位置。
顶层主脑可以说“我想执行这个动作”，但真正能不能执行、
要不要先审批、是否只能 probe、是否缺少前置条件，
都要先经过这里。

它负责的是“执行治理”，不是“业务思考”。
"""

from .http_contract_validator import (
    HttpContractValidationError,
    HttpContractValidator,
)
from .sql_verifier import SqlVerifier

__all__ = [
    "HttpContractValidationError",
    "HttpContractValidator",
    "SqlVerifier",
]
