"""通用数据字典模型（映射已有的 rtp_dict 表）。

这是一张已存在的外部字典表，xagent 只做只读映射，不负责建表和迁移。
通过 DICTTYPE 区分不同字典类别，如：
- ENV_TYPE：部署环境（YD01、TS01、CI01 等）

联合主键：(DICTTYPE, DICTCODE, LOCALE)
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Numeric
from .database import Base


class RtpDict(Base):  # type: ignore
    """通用数据字典（只读映射）。

    关键字段：
    - `DICTTYPE`：字典类别标识，如 ENV_TYPE
    - `DICTCODE`：字典编码，如 YD01
    - `DICTVALUE`：字典值/显示名称，如 "YD01环境"
    - `STATUS`：启用状态，1=启用 0=停用
    """

    __tablename__ = "rtp_dict"

    DICTTYPE = Column(String(32), primary_key=True, nullable=False, comment="数据字典ID")
    DICTCODE = Column(String(50), primary_key=True, nullable=False, comment="数据字典代码")
    LOCALE = Column(String(20), primary_key=True, nullable=False, comment="语言种类")
    DICTVALUE = Column(String(1000), nullable=True, comment="数据字典值")
    DEFAULTVALUE = Column(String(255), nullable=True, comment="默认值")
    ORDER_SEQ = Column(Numeric(3, 0), nullable=True, comment="排序序号")
    DICTDESCRIPT = Column(String(255), nullable=True, comment="描述")
    DICTTYPENAME = Column(String(255), nullable=True)
    STATUS = Column(Integer, nullable=False, default=1, comment="0-停用,1-启用")
    MODIFY_TIME = Column(DateTime, nullable=True, comment="修改时间")
    MODIFY_USER = Column(String(32), nullable=True, comment="修改人")
