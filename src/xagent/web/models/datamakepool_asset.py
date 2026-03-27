"""Datamakepool 通用资产模型。

该模型是造数平台里所有“可复用执行能力”的统一入口。
当前一张表同时承载：

1. `http` 资产：可直接发起 HTTP 请求的接口定义
2. `dubbo` 资产：可调用 Dubbo 服务的方法定义
3. `sql` 资产：可执行的 SQL 能力模板
4. `datasource` 资产：SQL 资产依赖的数据源连接信息

这样设计的原因是：
- 前台资产管理可以共用一套增删改查与权限模型
- 运行时账本里只需要引用一个 `asset_id`
- 后续做审批、版本、审计时可以共享基础字段
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from .database import Base


class DataMakepoolAsset(Base):  # type: ignore
    """造数平台资产主表。

    边界说明：
    - 这里只保存“资产元信息 + 结构化 config”，不直接保存运行结果
    - 不同 `asset_type` 的细节全部放在 `config` 中，由上层 validator 负责校验
    - `version` 用于标识资产定义是否发生变更，便于运行时留痕和前端提示
    """

    __tablename__ = "datamakepool_assets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    # 资产类型决定 config 的解释方式，也是 resolver / executor 的分流依据。
    asset_type = Column(String(20), nullable=False)
    # 宿主业务系统简称，用于隔离不同业务域下的资产可见范围。
    system_short = Column(String(50), nullable=False, index=True)
    # 状态只描述“资产定义是否可被选择”，不代表最近一次执行状态。
    status = Column(String(20), nullable=False)
    description = Column(Text, nullable=True)
    # 结构化配置快照，按 asset_type 存放 HTTP / Dubbo / SQL / datasource 专属字段。
    config = Column(JSON, nullable=True)
    # SQL 资产引用 datasource 资产时会回填该字段，其他类型通常为空。
    datasource_asset_id = Column(
        Integer, ForeignKey("datamakepool_assets.id"), nullable=True
    )
    # 敏感级别由治理层消费，后续可用于审批、脱敏或更严格的权限收缩。
    sensitivity_level = Column(String(20), nullable=True)
    # 每次更新资产定义都递增，供前端识别“是否已变更”以及审计记录引用。
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
