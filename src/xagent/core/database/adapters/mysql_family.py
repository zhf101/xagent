"""MySQL 兼容族 adapter。"""

from __future__ import annotations

from sqlalchemy import URL

from .sqlalchemy_common import SqlAlchemySyncAdapter


class MySqlFamilyAdapter(SqlAlchemySyncAdapter):
    family = "mysql"
    supported_types = ("mysql", "tidb", "oceanbase", "polardb", "goldendb")

    def build_sqlalchemy_url(self) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.config.user,
            password=self.config.password,
            host=self.config.host,
            port=self.config.port or 3306,
            database=self.config.database,
            query=self.config.extra or {},
        )
